import json
import boto3
import uuid
import time
from datetime import datetime, timezone
from botocore.exceptions import ClientError

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("HospitalResource")
event_table = dynamodb.Table("ProcessedEvents")

VALID_STATUS = ["EN_ROUTE", "ARRIVED", "CANCELLED"]
VALID_TRIAGE = ["RED", "YELLOW", "GREEN", "BLACK"]


# =========================
# TIME
# =========================
def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# =========================
# LOG HELPER
# =========================
def log(event, **kwargs):
    print(json.dumps({"event": event, **kwargs}))


# =========================
# VALIDATION
# =========================
def validate_message(message):
    for field in ["hospital_id", "triage_level", "status"]:
        if field not in message:
            raise ValueError(f"Missing field: {field}")

    if message["status"] not in VALID_STATUS:
        raise ValueError("Invalid status")

    if message["triage_level"] not in VALID_TRIAGE:
        raise ValueError("Invalid triage")


# =========================
# IDEMPOTENCY
# =========================
def idempotency_guard(trace_id):
    try:
        event_table.put_item(
            Item={
                "traceId": trace_id,
                "status": "PROCESSING",
                "ttl": int(time.time()) + 7 * 24 * 60 * 60
            },
            ConditionExpression="attribute_not_exists(traceId)"
        )
        return "NEW"

    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise e

        item = event_table.get_item(
            Key={"traceId": trace_id}
        ).get("Item")

        return item.get("status", "DONE") if item else "NEW"


def mark_done(trace_id):
    event_table.update_item(
        Key={"traceId": trace_id},
        UpdateExpression="SET #s = :d",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":d": "DONE"}
    )


# =========================
# TRIAGE MAP
# =========================
def map_triage(triage):
    if triage == "RED":
        return "ICU_BED"
    if triage in ["YELLOW", "GREEN"]:
        return "GENERAL_BED"
    if triage == "BLACK":
        return None
    return None


# =========================
# DELTA
# =========================
def get_delta(status):
    if status == "EN_ROUTE":
        return 1, 0
    if status == "CANCELLED":
        return -1, 0
    if status == "ARRIVED":
        return -1, -1
    return 0, 0


# =========================
# STATUS CALC
# =========================
def calc_status(effective, warning, critical):
    if effective <= critical:
        return "CRITICAL"
    if effective <= warning:
        return "WARNING"
    return "NORMAL"


# =========================
# UPDATE
# =========================
def update_resource(hospital_id, resource_type, dr, da, status):
    item = table.get_item(
        Key={"hospitalId": hospital_id, "resourceType": resource_type}
    ).get("Item")

    if not item:
        raise ValueError("Resource not found")

    reserved = int(item["reservedQuantity"])
    available = int(item["availableQuantity"])

    new_reserved = reserved + dr
    new_available = available + da

    if new_reserved < 0 or new_available < 0:
        raise ValueError("Invalid resource update")

    return table.update_item(
        Key={"hospitalId": hospital_id, "resourceType": resource_type},
        UpdateExpression="""
            SET reservedQuantity = :r,
                availableQuantity = :a,
                resourceStatus = :s,
                lastUpdatedTime = :t
        """,
        ExpressionAttributeValues={
            ":r": new_reserved,
            ":a": new_available,
            ":s": status,
            ":t": now_iso()
        },
        ReturnValues="ALL_NEW"
    )


# =========================
# HANDLER
# =========================
def lambda_handler(event, context):

    try:
        for record in event.get("Records", []):

            body = json.loads(record["body"])
            message = json.loads(body["Message"])

            trace_id = message.get("traceId") or str(uuid.uuid4())

            log("event_received", traceId=trace_id, message=message)

            # normalize field
            message = {
                "hospital_id": message.get("hospital_id") or message.get("hospitalId"),
                "triage_level": message.get("triage_level") or message.get("triage"),
                "status": message.get("status"),
                "traceId": trace_id
            }

            # validate
            validate_message(message)

            # idempotency
            state = idempotency_guard(trace_id)

            log("idempotency_check", traceId=trace_id, state=state)

            if state == "DONE":
                log("duplicate_skipped", traceId=trace_id)
                continue

            hospital_id = message["hospital_id"]
            triage = message["triage_level"]
            status = message["status"]

            resource_type = map_triage(triage)

            # =========================
            # BLACK CASE
            # =========================
            if resource_type is None:
                log("black_case_ignored", traceId=trace_id, triage=triage)
                mark_done(trace_id)
                continue

            item = table.get_item(
                Key={"hospitalId": hospital_id, "resourceType": resource_type}
            ).get("Item")

            if not item:
                raise ValueError("Resource not found")

            available = int(item["availableQuantity"])
            reserved = int(item["reservedQuantity"])

            warning = int(item["warningThreshold"])
            critical = int(item["criticalThreshold"])

            dr, da = get_delta(status)

            if status == "ARRIVED" and (reserved <= 0 or available <= 0):
                raise ValueError("Invalid ARRIVED state")

            new_effective = (available + da) - (reserved + dr)
            new_status = calc_status(new_effective, warning, critical)

            log("resource_update_calculated",
                traceId=trace_id,
                old_available=available,
                old_reserved=reserved,
                change_reserved=dr,
                change_available=da,
                new_status=new_status
            )

            update_resource(hospital_id, resource_type, dr, da, new_status)

            mark_done(trace_id)

            log("done", traceId=trace_id)

        return {"status": "ok"}

    except Exception as e:
        log("error", error=str(e))
        raise