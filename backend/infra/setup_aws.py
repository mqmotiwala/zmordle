"""
Idempotent provisioning for the Wordle Scoreboard backend.

Creates (or no-ops if they already exist):
  - S3 bucket            aws-wordle-scoreboard
  - DynamoDB table       results-wordle-scoreboard   (PK: puzzle [N], on-demand)
  - IAM role             wordle-scoreboard-lambda-role (+ inline least-priv policy)
  - Lambda               update-scores-wordle-scoreboard   (S3-triggered)
  - Lambda               build-analytics-wordle-scoreboard (invoked by the above)
  - S3 -> Lambda notification on the `exports/` prefix

Credentials are read from the repo-root .env (never printed). Safe to re-run:
existing resources are updated in place where it makes sense (Lambda code/config).

Usage:
    python backend/infra/setup_aws.py
"""

import io
import os
import json
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())

REGION = os.environ.get("AWS_REGION", "us-west-2")

# --- resource names ----------------------------------------------------------
BUCKET = "aws-wordle-scoreboard"
TABLE = "results-wordle-scoreboard"
ROLE_NAME = "wordle-scoreboard-lambda-role"
FN_UPDATE = "update-scores-wordle-scoreboard"
FN_ANALYTICS = "build-analytics-wordle-scoreboard"

EXPORT_PREFIX = "exports/"
ANALYTICS_KEY = "analytics/scoreboard.json"

LAMBDAS_DIR = Path(__file__).resolve().parents[1] / "lambdas"
RUNTIME = "python3.12"
HANDLER = "lambda_function.lambda_handler"

session = boto3.Session(region_name=REGION)
s3 = session.client("s3")
ddb = session.client("dynamodb")
iam = session.client("iam")
lam = session.client("lambda")
sts = session.client("sts")

ACCOUNT_ID = sts.get_caller_identity()["Account"]
ROLE_ARN = f"arn:aws:iam::{ACCOUNT_ID}:role/{ROLE_NAME}"
TABLE_ARN = f"arn:aws:dynamodb:{REGION}:{ACCOUNT_ID}:table/{TABLE}"
FN_ANALYTICS_ARN = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{FN_ANALYTICS}"


def log(msg):
    print(f"[setup] {msg}")


# --- S3 ----------------------------------------------------------------------
def ensure_bucket():
    try:
        s3.head_bucket(Bucket=BUCKET)
        log(f"S3 bucket '{BUCKET}' already exists.")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] not in ("404", "NoSuchBucket", "403"):
            raise

    kwargs = {"Bucket": BUCKET}
    if REGION != "us-east-1":
        kwargs["CreateBucketConfiguration"] = {"LocationConstraint": REGION}
    s3.create_bucket(**kwargs)
    s3.put_public_access_block(
        Bucket=BUCKET,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True, "IgnorePublicAcls": True,
            "BlockPublicPolicy": True, "RestrictPublicBuckets": True,
        },
    )
    log(f"Created S3 bucket '{BUCKET}'.")


# --- DynamoDB ----------------------------------------------------------------
def ensure_table():
    try:
        ddb.describe_table(TableName=TABLE)
        log(f"DynamoDB table '{TABLE}' already exists.")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    ddb.create_table(
        TableName=TABLE,
        AttributeDefinitions=[{"AttributeName": "puzzle", "AttributeType": "N"}],
        KeySchema=[{"AttributeName": "puzzle", "KeyType": "HASH"}],
        BillingMode="PAY_PER_REQUEST",
    )
    log(f"Creating DynamoDB table '{TABLE}'...")
    ddb.get_waiter("table_exists").wait(TableName=TABLE)
    log(f"Table '{TABLE}' is active.")


# --- IAM ---------------------------------------------------------------------
def ensure_role():
    trust = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    }
    created = False
    try:
        iam.get_role(RoleName=ROLE_NAME)
        log(f"IAM role '{ROLE_NAME}' already exists.")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise
        iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Execution role for Wordle Scoreboard Lambdas.",
        )
        created = True
        log(f"Created IAM role '{ROLE_NAME}'.")

    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "Logs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                ],
                "Resource": "arn:aws:logs:*:*:*",
            },
            {
                "Sid": "S3",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
                "Resource": [
                    f"arn:aws:s3:::{BUCKET}",
                    f"arn:aws:s3:::{BUCKET}/*",
                ],
            },
            {
                "Sid": "DynamoDB",
                "Effect": "Allow",
                "Action": [
                    "dynamodb:Scan", "dynamodb:GetItem", "dynamodb:PutItem",
                    "dynamodb:BatchWriteItem", "dynamodb:UpdateItem",
                    "dynamodb:Query",
                ],
                "Resource": [TABLE_ARN, f"{TABLE_ARN}/*"],
            },
            {
                "Sid": "InvokeAnalytics",
                "Effect": "Allow",
                "Action": "lambda:InvokeFunction",
                "Resource": FN_ANALYTICS_ARN,
            },
        ],
    }
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="wordle-scoreboard-inline",
        PolicyDocument=json.dumps(policy),
    )
    log("Attached inline policy to role.")

    if created:
        log("Waiting for IAM role to propagate...")
        time.sleep(12)


# --- Lambda packaging --------------------------------------------------------
def zip_lambda(dir_name):
    src = LAMBDAS_DIR / dir_name
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for py in sorted(src.glob("*.py")):
            zf.write(py, arcname=py.name)
    buf.seek(0)
    return buf.read()


def ensure_function(name, dir_name, env_vars):
    code = zip_lambda(dir_name)
    config = dict(
        FunctionName=name,
        Runtime=RUNTIME,
        Role=ROLE_ARN,
        Handler=HANDLER,
        Timeout=60,
        MemorySize=256,
        Environment={"Variables": env_vars},
    )

    exists = True
    try:
        lam.get_function(FunctionName=name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        exists = False

    if not exists:
        # newly created roles can take a moment to be assumable
        for attempt in range(6):
            try:
                lam.create_function(Code={"ZipFile": code}, Publish=True, **config)
                log(f"Created Lambda '{name}'.")
                break
            except ClientError as e:
                msg = e.response["Error"].get("Message", "")
                if "cannot be assumed" in msg or "role defined" in msg:
                    log(f"Role not ready, retrying ({attempt + 1}/6)...")
                    time.sleep(8)
                    continue
                raise
        else:
            raise RuntimeError(f"Could not create '{name}' (role assumption).")
    else:
        lam.update_function_code(FunctionName=name, ZipFile=code, Publish=True)
        lam.get_waiter("function_updated").wait(FunctionName=name)
        lam.update_function_configuration(
            FunctionName=name, Runtime=RUNTIME, Role=ROLE_ARN, Handler=HANDLER,
            Timeout=60, MemorySize=256, Environment={"Variables": env_vars},
        )
        lam.get_waiter("function_updated").wait(FunctionName=name)
        log(f"Updated Lambda '{name}'.")


# --- S3 -> Lambda notification ----------------------------------------------
def ensure_s3_trigger():
    statement_id = "s3invoke-update-scores"
    try:
        lam.add_permission(
            FunctionName=FN_UPDATE,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="s3.amazonaws.com",
            SourceArn=f"arn:aws:s3:::{BUCKET}",
            SourceAccount=ACCOUNT_ID,
        )
        log("Granted S3 permission to invoke update-scores Lambda.")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            log("S3 invoke permission already present.")
        else:
            raise

    fn_arn = f"arn:aws:lambda:{REGION}:{ACCOUNT_ID}:function:{FN_UPDATE}"
    notification = {
        "LambdaFunctionConfigurations": [{
            "Id": "wordle-export-upload",
            "LambdaFunctionArn": fn_arn,
            "Events": ["s3:ObjectCreated:*"],
            "Filter": {"Key": {"FilterRules": [
                {"Name": "prefix", "Value": EXPORT_PREFIX},
            ]}},
        }]
    }
    # S3 validates it can invoke the Lambda; the add_permission above may need a
    # few seconds to propagate, so retry on the transient validation error.
    for attempt in range(6):
        try:
            s3.put_bucket_notification_configuration(
                Bucket=BUCKET, NotificationConfiguration=notification,
            )
            log(f"Configured S3 notification on '{EXPORT_PREFIX}'.")
            return
        except ClientError as e:
            if e.response["Error"]["Code"] == "InvalidArgument":
                log(f"Permission not propagated yet, retrying ({attempt + 1}/6)...")
                time.sleep(8)
                continue
            raise
    raise RuntimeError("Could not configure S3 notification after retries.")


def main():
    log(f"Account {ACCOUNT_ID}, region {REGION}")
    ensure_bucket()
    ensure_table()
    ensure_role()
    ensure_function(
        FN_ANALYTICS, "build_analytics",
        {"RESULTS_TABLE": TABLE, "BUCKET": BUCKET, "ANALYTICS_KEY": ANALYTICS_KEY},
    )
    ensure_function(
        FN_UPDATE, "update_scores",
        {"RESULTS_TABLE": TABLE, "EXPORT_PREFIX": EXPORT_PREFIX,
         "ANALYTICS_FUNCTION": FN_ANALYTICS},
    )
    ensure_s3_trigger()
    log("Done.")


if __name__ == "__main__":
    main()
