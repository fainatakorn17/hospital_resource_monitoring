import json
import boto3
import uuid


dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('HospitalResource')

def map_triage(triage):
    if triage == "RED":
        return "ICU_BED"
    elif triage in ["YELLOW", "GREEN"]:
        return "GENERAL_BED"
    else:
        return None  # BLACK

def lambda_handler(event, context):
    try:
        for record in event.get("Records", []):
            sns_data = record.get("Sns", {})
            message = json.loads(sns_data.get("Message", "{}"))

            trace_id = message.get("traceId") or str(uuid.uuid4())

            hospital_id = message.get("hospital_id")
            triage = message.get("triage_level")
            status = message.get("status")

            print(json.dumps({
                "traceId": trace_id,
                "event": "event_received",
                "hospitalId": hospital_id,
                "triage": triage,
                "status": status
            }, default=int))

            # ignore BLACK
            resource_type = map_triage(triage)
            if not resource_type:
                print(f"[{trace_id}] BLACK case ignored")
                continue

            # get item
            response = table.get_item(
                Key={
                    "hospitalId": hospital_id,
                    "resourceType": resource_type
                }
            )

            item = response.get("Item")
            if not item:
                print(f"[{trace_id}] Resource not found")
                continue

            available = item["availableQuantity"]
            reserved = item.get("reservedQuantity", 0)

            # logic
            if status == "EN_ROUTE":
                reserved += 1

            elif status == "CANCELLED":
                if reserved > 0:
                    reserved -= 1

            elif status == "ARRIVED":
                if reserved > 0:
                    reserved -= 1
                if available > 0:
                    available -= 1

            # calculate
            effective = available - reserved

            if effective <= item["criticalThreshold"]:
                new_status = "CRITICAL"
            elif effective <= item["warningThreshold"]:
                new_status = "WARNING"
            else:
                new_status = "NORMAL"

            # update DB
            table.update_item(
                Key={
                    "hospitalId": hospital_id,
                    "resourceType": resource_type
                },
                UpdateExpression="""
                    SET availableQuantity = :a,
                        reservedQuantity = :r,
                        resourceStatus = :s
                """,
                ExpressionAttributeValues={
                    ":a": available,
                    ":r": reserved,
                    ":s": new_status
                }
            )

            print(json.dumps({
                "traceId": trace_id,
                "event": "resource_updated",
                "hospitalId": hospital_id,
                "resourceType": resource_type,
                "available": available,
                "reserved": reserved,
                "status": new_status
            }, default=int))

        return {"status": "ok"}

    except Exception as e:
        print(json.dumps({
            "traceId": "UNKNOWN",
            "error": str(e)
        }, default=int))
        raise e