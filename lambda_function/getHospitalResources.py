import json
import boto3
import uuid
from boto3.dynamodb.conditions import Key


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

    hospital_id = event["pathParameters"]["hospitalId"]
    if not hospital_id:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "traceId": trace_id,
                "error": {
                    "errorCode": "INVALID_REQUEST",
                    "message": "hospitalId is required"
                }
            }, indent=2)
        }

    query_params = event.get("queryStringParameters") or {}
    status = query_params.get("status")
    resource_type = query_params.get("resourceType")

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
        response = table.query(
            KeyConditionExpression=Key("hospitalId").eq(hospital_id)
        )
        items = response.get("Items", [])

    except Exception as e:
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
    
    if len(items) == 0:
        return {
            "statusCode": 404,
            "body": json.dumps({
                "traceId": trace_id,
                "error": {
                    "errorCode": "HOSPITAL_NOT_FOUND",
                    "message": "Hospital not found"
                }
            }, indent=2)
        }

    if status:
        items = [i for i in items if i.get("resourceStatus") == status]
    if resource_type:
        items = [i for i in items if i.get("resourceType") == resource_type]

    resources = []

    for i in items:
        available = i.get("availableQuantity", 0)
        reserved = i.get("reservedQuantity", 0)
        effective = available - reserved
        effective = max(0, available - reserved)

        resources.append({
            "resourceType": i.get("resourceType"),
            "availableQuantity": available,
            "reservedQuantity": reserved,
            "effectiveAvailable": effective,
            "resourceStatus": i.get("resourceStatus"),
            "lastUpdatedTime": i.get("lastUpdatedTime")
        })

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json"
        },
        "body": json.dumps({
            "traceId": trace_id,
            "data": {
                "hospitalId": hospital_id,
                "resources": resources
            }
        }, default=int)
    }

