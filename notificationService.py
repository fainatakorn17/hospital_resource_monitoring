import json
import uuid

def lambda_handler(event, context):
    try:
        for record in event.get('Records', []):

            remaining_time = context.get_remaining_time_in_millis()
            if remaining_time < 1000:
                print("[SYSTEM] Timeout safety triggered, aborting")
                raise Exception("Timeout safety triggered")

            sns_data = record.get('Sns', {})
            message_str = sns_data.get('Message', '{}')
            message = json.loads(message_str)

            trace_id = message.get("traceId")

            # fallback: จาก MessageAttributes
            if not trace_id:
                trace_id = sns_data.get('MessageAttributes', {}).get('traceId', {}).get('Value')

            # fallback สุดท้าย (กันพัง)
            if not trace_id:
                trace_id = str(uuid.uuid4())

            event_type = sns_data.get('MessageAttributes', {}).get('eventType', {}).get('Value', 'UNKNOWN')

            print(f"""
            [traceId={trace_id}] 📩 Event: {event_type}
            Hospital: {message.get('hospitalId')}
            Resource: {message.get('resourceType')}
            Available: {message.get('availableQuantity')}
            Status: {message.get('resourceStatus')}
            ⏰ Time: {message.get('lastUpdatedTime')}
            """)

            if event_type == "ResourceStatusAlertEvent":
                print(f"[{trace_id}] 🚨 ALERT TRIGGERED")
            elif event_type == "ResourceAvailabilityUpdatedEvent":
                print(f"[{trace_id}] 📊 AVAILABILITY UPDATED")
            else:
                print(f"[{trace_id}] ❓ Unknown event")

        return {"status": "ok"}

    except Exception as e:
        print(f"[traceId={trace_id if 'trace_id' in locals() else 'UNKNOWN'}] ❌ ERROR: {str(e)}")
        raise e  

