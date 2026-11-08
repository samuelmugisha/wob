# Backing up the server and moving to Hugging Face

The production system runs on the DigitalOcean server (`infrastructure/deployment/`). This guide
backs that server up, then runs the same system as a Hugging Face Docker Space restored from the
backup.

## What moves where

| What | Where it goes | Who can read it |
| --- | --- | --- |
| Database dump and encrypted files | A **private** Hugging Face dataset (`you/wob-backups`) | Your HF account, and the Space through its `HF_TOKEN` |
| `SECRET_KEY`, `FILE_ENCRYPTION_KEYS` and other server secrets | Space **secrets** (never the dataset) | The running Space only |
| App code | The Space repository | Anyone, if the Space is public |

The files stay encrypted in the dataset. They can be read only with `FILE_ENCRYPTION_KEYS`, which
are kept apart from the data.

## 1. Back up the server

```bash
infrastructure/deployment/backup.sh root@139.59.160.17
```

This writes `~/wob-backups/<timestamp>/` (the `wob.dump` database dump, the `storage/` folder
and `counts.txt`). The server's env file goes to `~/wob-backups/keys/env-<timestamp>`. Keep that
file somewhere other than the data, for example a password manager. Set `BACKUP_DIR` to write
somewhere other than `~/wob-backups`.

## 2. Upload the backup to a private dataset

```bash
hf auth login   # once, with a token that has write access
uv run --no-project --with huggingface_hub python infrastructure/huggingface/hub.py \
  upload-backup ~/wob-backups/<timestamp> --dataset <you>/wob-backups
```

The script creates the dataset as private and refuses to upload if the dataset is public. Each
backup is a folder `<timestamp>/` holding `wob.dump` and `storage.tar`. The file `LATEST` names
the newest backup.

## 3. Create the Space

1. On huggingface.co, create a **fine-grained token** for the Space with *read* access to the
   `wob-backups` dataset. Give it *write* access as well if you will turn on `BACKUP_UPLOAD`
   (step 5).
2. Push the app. This copies the server secrets into the Space and points the Space at the dataset:

   ```bash
   SPACE_HF_TOKEN=hf_xxx uv run --no-project --with huggingface_hub \
     python infrastructure/huggingface/hub.py push-space \
     --space <you>/wob-awards --dataset <you>/wob-backups \
     --env ~/wob-backups/keys/env-<timestamp>
   ```

   The Space is public by default. Add `--private` to create it private.
3. In the Space's **Settings**:
   - **Persistent storage.** Add it (it is mounted at `/data`). Without it, every restart reloads
     the backup and loses everything done since. The start-up log warns when it is missing.
   - **Hardware.** The free *CPU basic* tier (2 vCPU, 16 GB) runs the system, but it sleeps after
     about two days without visitors, and the next visit waits several minutes for it to start.
     Paid hardware can stay awake.

The first start takes a while. It builds the image, downloads and restores the backup, loads the
ClamAV signatures and downloads the embedding and reranking models. Follow it in the **Logs**
tab. A line like `data from backup 20261108-120000: 42 finalists, 310 stored files` means the
restore is done. Compare the numbers with `counts.txt`.

Then sign in at `https://<you>-wob-awards.hf.space`. Sign-in does not work inside the
huggingface.co page, because the session cookie is `SameSite=Strict` and the app is shown in a
frame there. Invitation links use this address (`PUBLIC_BASE_URL`, set from the Space host).

## 4. Cut over from DigitalOcean

While both systems run, changes made on the server do not reach the Space. To switch over:

1. Tell users to stop working on the server, then run `backup.sh` and `upload-backup` again.
2. In the Space's settings, set the variable `RESTORE_BACKUP` to the new backup's timestamp. The
   Space restarts and restores that backup. Its previous data is moved to `/data/previous`; it
   is not deleted.
3. Check the counts in the log, then announce the new address. Stop the DigitalOcean stack only
   once the Space has run correctly for a while, and keep the last server backup.

`RESTORE_BACKUP` is acted on only when it differs from the backup in use, so leaving it set is
safe. Once users work in the Space, its own data is the original. Restoring an older backup
overwrites their work. The data kept in `/data/previous` is the only way back.

## 5. Ongoing backups from the Space

Set the variable `BACKUP_UPLOAD=true`. The Space token also needs write access to the dataset.
The Space then uploads a dump and the encrypted files every `BACKUP_INTERVAL_HOURS` hours
(default 24) as `space-<timestamp>/`, and marks each upload as `LATEST`. To restore one, set
`RESTORE_BACKUP` to its name.

## Updating the app

Run `push-space` again. It mirrors the current `backend/` and `frontend/` and rebuilds the Space.
Migrations run on start, as on the server. `--env` can be left out when the secrets are
unchanged.

## Differences from the DigitalOcean deployment

- **One container.** PostgreSQL, ClamAV, the API, the worker and the web UI run together
  (`infrastructure/huggingface/space/start.sh`). If one of them stops, the Space restarts.
- **Outgoing email.** Hugging Face Spaces may block outgoing SMTP connections, including on port
  2525. If invitation emails fail, set `EMAIL_BACKEND=disabled`, and admins then share the link
  shown on screen.
- **Hosting location.** The system and its personal data move to Hugging Face's infrastructure.
  Under the data protection review (§4.6, §4.8), that is processing outside Uganda. Record the
  decision, sign a data processing agreement with Hugging Face, and name Hugging Face as the
  hosting provider in the finalist notice.
- **Public Space.** A public Space shows its source code and the sign-in page to anyone. The data
  is protected by the app's accounts and two-factor sign-in. To restrict who can reach the
  Space, make it private.
