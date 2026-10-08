# Optional Garmin module

The module exposes three read-only tools using the unofficial `garminconnect` library: daily statistics for a date, sleep for a date, and up to 20 recent activities. It uses your personal Garmin Connect session tokens. It is independent code, not a fork or full port of a Garmin MCP server, and has not been tested against a real account yet.

## Enable

Edit `config/modules.json` through the GitHub web editor:

```json
{"enabled": ["example", "garmin"]}
```

Commit and run the deploy workflow. Terraform creates an empty Secrets Manager secret and passes its ARN to the Garmin Lambda. No password or token is read into Terraform state. Copy `garmin_secret_arn` from the apply summary.

## Login from AWS CloudShell

The pinned Garmin library requires Python 3.12. In your fork checkout in CloudShell on Amazon Linux 2023, install that interpreter if necessary, create a virtual environment, and install the reviewed, hash-locked wheel dependencies:

```bash
sudo dnf install -y python3.12 python3.12-pip
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes --only-binary=:all: -r modules/garmin/requirements.lock
python scripts/garmin_login.py --region eu-west-1 --secret-arn YOUR-SECRET-ARN
```

System packages outside the CloudShell home directory may need reinstalling in a future session. [Amazon Linux Python versions](https://docs.aws.amazon.com/linux/al2023/ug/python.html).

The login helper requires an interactive terminal, prompts for email, password and MFA without echo, verifies the serialized token session, and writes it directly to the existing AWS secret. It does not save token files or send credential values to GitHub. Add `--china` only for a Garmin China account. Your CloudShell identity needs `secretsmanager:PutSecretValue` for the secret.

If the third-party login fails, the helper returns a safe error. Check Garmin account/MFA requirements and AWS permissions. The unofficial login can also be affected by upstream changes or network restrictions; these have not been live-tested from CloudShell.

## Token refresh and concurrency

Each tool call reloads the secret, reads Garmin data, and saves changed serialized tokens back to the same secret. Credentials and upstream exceptions are suppressed from logs. Expired/revoked sessions may still require rerunning the login helper.

By default, Lambda concurrency is unreserved so the module can deploy on new personal accounts with low quotas. Simultaneous calls can race when refreshing tokens; this preview does not implement distributed locking. For personal sequential use, avoid parallel calls during token renewal. If the account has enough unreserved concurrency, set GitHub variable `GARMIN_RESERVED_CONCURRENCY` to `1` and reapply to serialize Garmin calls.

AWS requires at least 100 concurrency units to remain unreserved; reserving one requires at least 101 available units. A fresh account can have a lower limit, so the kit does not force this reservation. This is a concurrency limit, not provisioned concurrency, and carries no capacity fee. [AWS concurrency configuration](https://docs.aws.amazon.com/lambda/latest/dg/configuration-concurrency.html).

The optional secret has a published $0.40/month storage price plus request charges, separately from Gateway/Lambda costs. Removing Garmin schedules the secret for deletion with a seven-day recovery window. Reenabling it during that window can require restoring/importing the secret.

## Data access

All authorized users of this deployment use the same Garmin account. Do not add other Cognito users expecting account isolation. Tool results are sent to the MCP client you connect and may enter its model context. Read the [security notes](security.md) before using personal health data.

References: [python-garminconnect](https://github.com/cyberjunky/python-garminconnect), [Garmin developer program](https://developer.garmin.com/gc-developer-program/overview/).
