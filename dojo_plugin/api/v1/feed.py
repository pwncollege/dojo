import json
import time
import redis
from flask import Response, request, current_app
from flask_restx import Namespace, Resource
from ...utils.feed import get_recent_events

feed_namespace = Namespace("feed", description="Activity feed endpoints")


@feed_namespace.route("/events")
class FeedEvents(Resource):
    def get(self):
        try:
            limit = min(int(request.args.get("limit", 50)), 100)
            offset = max(int(request.args.get("offset", 0)), 0)
        except (ValueError, TypeError):
            limit, offset = 50, 0
        dojo_id = request.args.get("dojo")
        events = get_recent_events(limit=limit, offset=offset, dojo_id=dojo_id)
        return {"success": True, "data": events, "meta": {"limit": limit, "offset": offset, "count": len(events)}}


@feed_namespace.route("/stream")
class FeedStream(Resource):
    def get(self):
        redis_url = current_app.config.get("REDIS_URL", "redis://cache:6379")
        dojo_id = request.args.get("dojo")
        
        def generate():
            r = redis.from_url(redis_url, decode_responses=True)
            pubsub = r.pubsub()
            pubsub.subscribe("activity_feed:live")
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            last_heartbeat = time.time()
            
            try:
                while True:
                    message = pubsub.get_message(timeout=1)
                    if message and message['type'] == 'message':
                        try:
                            if dojo_id:
                                event = json.loads(message["data"])
                                if event.get("data", {}).get("dojo_id") != dojo_id:
                                    continue
                            yield f"data: {message['data']}\n\n"
                        except (TypeError, ValueError):
                            continue
                    if time.time() - last_heartbeat > 30:
                        yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                        last_heartbeat = time.time()
            except GeneratorExit:
                pubsub.close()
                raise
            except Exception:
                pubsub.close()
                
        return Response(generate(), mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
