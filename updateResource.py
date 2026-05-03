import json
import boto3
import uuid
import urllib3
from boto3.dynamodb.conditions import Key
from datetime import datetime, timezone

http = urllib3.PoolManager()

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('HospitalResource')
hospital_table = dynamodb.Table('HospitalInformation')

sns = boto3.client('sns')
AVAILABILITY_TOPIC_ARN = "arn:aws:sns:us-east-1:484183391590:hospital-resource-availability-updated"
ALERT_TOPIC_ARN = "arn:aws:sns:us-east-1:484183391590:hospital-resource-status-alert"

def get_trace_id(event):
    headers = event.get("headers") or {}
    trace_id = headers.get("X-Trace-Id")

    if not trace_id:
        trace_id = str(uuid.uuid4())

    return trace_id

def request_resource(trace_id, hospital_id, resource_type, hospital_info):
    url = "https://re-e6234552945c4020abfbf244b45240fc.ecs.ap-southeast-7.on.aws/v1/resource/"

    payload = {
        "incidentId": str(uuid.uuid4()),
        "description": f"{resource_type} is running low",
        "requestFor": resource_type,
        "items": [
            {
                "id": resource_type,
                "amount": 1
            }
        ],
        "extraItems": [
            {
                "name": "",
                "amount": 1
            }
        ],
        "from": {
            "name": hospital_info.get("hospitalName"),
            "location": {
                "address": hospital_info.get("address"),
                "description": "Auto request",
                "latitude": hospital_info.get("latitude"),
                "longitude": hospital_info.get("longitude")
            },
            "contact": {
                "phone": hospital_info.get("contactNumber")
            }
        }
    }

    headers = {
        "Content-Type": "application/json",
        "idempotency-key": str(uuid.uuid4())
    }

    try:
        print(json.dumps({
            "traceId": trace_id,
            "event": "outgoing_request_payload",
            "payload": payload
        }, default=float))
        response = http.request(
            "POST",
            url,
            body=json.dumps(payload, default=float),
            headers=headers,
            timeout=2.0
        )

        print(json.dumps({
            "traceId": trace_id,
            "event": "resource_request_sent",
            "status_code": response.status,
            "response_body": response.data.decode("utf-8")
        }))

    except Exception as e:
        print(json.dumps({
            "traceId": trace_id,
            "event": "resource_request_failed",
            "error": str(e)
        }))

def lambda_handler(event, context):

    trace_id = get_trace_id(event)
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if context.get_remaining_time_in_millis() < 3000:
        print(json.dumps({
            "traceId": trace_id,
            "event": "timeout_guard_triggered"
        }))
        raise Exception("Timeout safety triggered")

    hospital_id = event["pathParameters"]["hospitalId"]
    resource_type = event["pathParameters"]["resourceType"]

    body = json.loads(event["body"])
    available_quantity = body.get("availableQuantity")

    print(json.dumps({
        "traceId": trace_id,
        "event": "request_received",
        "hospitalId": hospital_id,
        "resourceType": resource_type,
        "availableQuantity": available_quantity
    }))

    if available_quantity is None or available_quantity < 0:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "traceId": trace_id,
                "error": {
                    "errorCode": "INVALID_QUANTITY",
                    "message": "availableQuantity must be >= 0"
                }
            })
        }

    # ดึงข้อมูล resource เดิม
    response = table.get_item(
        Key={
            "hospitalId": hospital_id,
            "resourceType": resource_type
        }
    )

    item = response.get("Item")

    if not item:
        return {
            "statusCode": 404,
                "body": json.dumps({
                "traceId": trace_id,
                "error": {
                    "errorCode": "RESOURCE_NOT_FOUND",
                    "message": "Resource not found"
                }
            }, indent=2)
        }

    total_capacity = item["totalCapacity"]

    if available_quantity > total_capacity:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "traceId": trace_id,
                "error": {
                    "errorCode": "INVALID_QUANTITY",
                    "message": "Available quantity cannot exceed total capacity"
                }
            }, indent=2)
        }

    critical_threshold = item["criticalThreshold"]
    warning_threshold = item["warningThreshold"]

    reserved = item.get("reservedQuantity", 0)
    effective = available_quantity - reserved

    if effective < 0:
        return {
            "statusCode": 400,
            "body": json.dumps({
                "traceId": trace_id,
                "error": {
                    "errorCode": "INVALID_QUANTITY",
                    "message": "Available quantity cannot be less than reserved quantity"
                }
            })
        }

    if effective <= critical_threshold:
        status = "CRITICAL"
    elif effective <= warning_threshold:
        status = "WARNING"
    else:
        status = "NORMAL"

    # update DynamoDB
    table.update_item(
        Key={
            "hospitalId": hospital_id,
            "resourceType": resource_type
        },
        UpdateExpression="""
            SET availableQuantity = :q,
                resourceStatus = :s,
                lastUpdatedTime = :t
        """,
        ExpressionAttributeValues={
            ":q": available_quantity,
            ":s": status,
            ":t": current_time
        }
    )

    print(json.dumps({
        "traceId": trace_id,
        "event": "db_updated",
        "hospitalId": hospital_id,
        "resourceType": resource_type,
        "status": status
    }))

    event_message = {
        "traceId": trace_id,
        "hospitalId": hospital_id,
        "resourceType": resource_type,
        "totalCapacity": int(total_capacity),
        "availableQuantity": int(available_quantity),
        "resourceStatus": status,
        "lastUpdatedTime": current_time
    }
    hospital_info = hospital_table.get_item(
        Key={"hospitalId": hospital_id}
    ).get("Item")

    if not hospital_info:
        print(json.dumps({
            "traceId": trace_id,
            "event": "hospital_info_not_found"
        }))
    old_status = item.get("resourceStatus")

    try:
        if context.get_remaining_time_in_millis() < 1000:
            print(json.dumps({
                "traceId": trace_id,
                "event": "timeout_guard_triggered_before_publish"
            }))
            raise Exception("Timeout before SNS publish")

        if status in ["WARNING", "CRITICAL"] and status != old_status:
            sns.publish(
                TopicArn=ALERT_TOPIC_ARN,
                Message=json.dumps(event_message),
                MessageAttributes={
                    "eventType": {
                        "DataType": "String",
                        "StringValue": "ResourceStatusAlertEvent"
                    },
                    "traceId": { 
                        "DataType": "String",
                        "StringValue": trace_id
                    }
                }        
            )
            print(json.dumps({
                "traceId": trace_id,
                "event": "alert_event_published",
                "hospitalId": hospital_id,
                "resourceType": resource_type,
                "status": status
            }))
        
        if status == "CRITICAL" and status != old_status:
            if context.get_remaining_time_in_millis() < 1500:
                print(json.dumps({
                    "traceId": trace_id,
                    "event": "skip_request_due_to_timeout"
                }))
            elif not hospital_info:
                print(json.dumps({
                    "traceId": trace_id,
                    "event": "skip_request_no_hospital_info"
                }))
            else:
                print(json.dumps({
                    "traceId": trace_id,
                    "event": "resource_request_triggered",
                    "hospitalId": hospital_id,
                    "resourceType": resource_type
                }))

                request_resource(trace_id, hospital_id, resource_type, hospital_info)
            
        sns.publish(
            TopicArn=AVAILABILITY_TOPIC_ARN,
            Message=json.dumps(event_message),
            MessageAttributes={
                "eventType": {
                    "DataType": "String",
                    "StringValue": "ResourceAvailabilityUpdatedEvent"
                },
                "traceId": {
                    "DataType": "String",
                    "StringValue": trace_id
                }
            }
        )

        print(json.dumps({
            "traceId": trace_id,
            "event": "availability_event_published",
            "hospitalId": hospital_id,
            "resourceType": resource_type,
            "status": status
        }))

    except Exception as e:
        print(json.dumps({
            "traceId": trace_id,
            "event": "❌ sns_publish_failed",
            "error": str(e)
        }))
        raise e

    return {
        "statusCode": 200,
        "body": json.dumps({
            "traceId": trace_id,
            "data": {
                "message": "Resource availability updated successfully",
                "resourceStatus": status
            }
        }, indent=2)
    }
