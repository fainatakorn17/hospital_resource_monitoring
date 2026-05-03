import json
import boto3
import uuid
from decimal import Decimal

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('HospitalInformation')

def get_trace_id(event):
    headers = event.get("headers") or {}
    trace_id = headers.get("X-Trace-Id")

    if not trace_id:
        trace_id = str(uuid.uuid4())

    return trace_id

def convert_decimal(obj):
    if isinstance(obj, list):
        return [convert_decimal(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: convert_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, Decimal):
        return float(obj)  
    else:
        return obj

def lambda_handler(event, context):

    trace_id = get_trace_id(event)

    try:
        # ดึง hospitalId จาก path
        hospital_id = event['pathParameters']['hospitalId']

        # Query DynamoDB
        response = table.get_item(
            Key={
                'hospitalId': hospital_id
            }
        )

        # เช็คว่ามีข้อมูลไหม
        if 'Item' not in response:
            return {
                'statusCode': 404,
                'body': json.dumps({
                    "traceId": trace_id,
                    "error": {
                        "errorCode": "HOSPITAL_NOT_FOUND",
                        "message": "Hospital not found"
                    }
                })
            }

        item = response['Item']
        item = convert_decimal(item)

        # return ข้อมูล
        return {
            'statusCode': 200,
            'body': json.dumps({
                "traceId": trace_id,
                "data": item
            }, indent=2)
        }

    except Exception as e:
        return {
            'statusCode': 500,
            'body': json.dumps({
                "traceId": trace_id,
                "error": {
                    "errorCode": "HOSPITAL_NOT_FOUND",
                    "message": "Hospital not found"
                }
            }, indent=2)
        }
