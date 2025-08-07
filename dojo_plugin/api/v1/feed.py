import json
import time
import logging
from queue import Queue, Empty
from threading import Event

from flask import Response, request, current_app
from flask_restx import Namespace, Resource
from CTFd.utils.decorators import admins_only

from ...utils.feed import get_recent_events, get_redis_client

logger = logging.getLogger(__name__)

feed_namespace = Namespace("feed", description="Activity feed endpoints")


@feed_namespace.route("/events")
class FeedEvents(Resource):
    def get(self):
        limit = min(int(request.args.get("limit", 50)), 100)
        offset = int(request.args.get("offset", 0))
        
        events = get_recent_events(limit=limit, offset=offset)
        
        return {
            "success": True,
            "data": events,
            "meta": {
                "limit": limit,
                "offset": offset,
                "count": len(events)
            }
        }


@feed_namespace.route("/stream")
class FeedStream(Resource):
    def get(self):
        def generate():
            r = get_redis_client()
            pubsub = r.pubsub()
            pubsub.subscribe("activity_feed:live")
            
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            
            last_heartbeat = time.time()
            
            try:
                while True:
                    message = pubsub.get_message(timeout=1)
                    
                    if message and message['type'] == 'message':
                        try:
                            event_data = json.loads(message['data'])
                            yield f"data: {json.dumps(event_data)}\n\n"
                        except json.JSONDecodeError:
                            logger.error(f"Failed to decode message: {message['data']}")
                    
                    if time.time() - last_heartbeat > 30:
                        yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                        last_heartbeat = time.time()
                        
            except GeneratorExit:
                pubsub.close()
                raise
            except Exception as e:
                logger.error(f"Error in SSE stream: {e}")
                pubsub.close()
                
        return Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive"
            }
        )