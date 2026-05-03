import json
import boto3
import uuid

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('HospitalResource')

def get_trace_id(event):
    headers = event.get("headers") or {}
    trace_id = headers.get("X-Trace-Id")

    if not trace_id:
        trace_id = str(uuid.uuid4())

    return trace_id

def lambda_handler(event, context):

    trace_id = get_trace_id(event)

    resource_type = event["pathParameters"]["resourceType"]
    status = event.get("queryStringParameters", {}).get("status")

    valid_status = ["NORMAL", "WARNING", "CRITICAL"]
    if status and status not in valid_status:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "traceId": trace_id,
                "error": {
                    "errorCode": "INVALID_STATUS_FILTER",
                    "message": "Status must be NORMAL, WARNING, or CRITICAL"
                }
            }, indent=2)
        }

    try:
        response = table.scan()
        items = response.get("Items", [])

    except Exception:
        return {
            "statusCode": 503,
            "body": json.dumps({
                "traceId": trace_id,
                "error": {
                    "errorCode": "SERVICE_TIMEOUT",
                    "message": "Temporary issue, please retry"
                }
            }, indent=2)
        }

    hospitals = []

    for i in items:
        if i.get("resourceType") != resource_type:
            continue

        available = i.get("availableQuantity", 0)
        reserved = i.get("reservedQuantity", 0)
        effective = max(0, available - reserved)

        hospitals.append({
            "hospitalId": i.get("hospitalId"),
            "availableQuantity": available,
            "reservedQuantity": reserved,
            "effectiveAvailable": effective,
            "resourceStatus": i.get("resourceStatus"),
            "lastUpdatedTime": i.get("lastUpdatedTime")
        })

    if len(hospitals) == 0:
        return {
            "statusCode": 404,
            "body": json.dumps({
                "traceId": trace_id,
                "error": {
                    "errorCode": "RESOURCE_NOT_FOUND",
                    "message": "No hospitals found for this resource type"
                }
            }, indent=2)
        }

    if status:
        hospitals = [
            h for h in hospitals
            if h.get("resourceStatus") == status
        ]

    return {
        "statusCode": 200,
        "body": json.dumps({
            "traceId": trace_id,
            "data": {
                "resourceType": resource_type,
                "hospitals": hospitals
            }
        }, indent=2, default=int)
    }

