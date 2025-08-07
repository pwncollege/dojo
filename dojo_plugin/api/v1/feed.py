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
        # Get Redis URL while we have app context
        import redis
        redis_url = current_app.config.get("REDIS_URL", "redis://cache:6379")
        
        def generate():
            r = redis.from_url(redis_url, decode_responses=True)
            pubsub = r.pubsub()
            pubsub.subscribe("activity_feed:live")
            
            # Send initial connected message
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            
            last_heartbeat = time.time()
            
            try:
                while True:
                    message = pubsub.get_message(timeout=1)
                    
                    if message:
                        if message['type'] == 'message':
                            try:
                                event_data = json.loads(message['data'])
                                yield f"data: {json.dumps(event_data)}\n\n"
                            except (json.JSONDecodeError, TypeError):
                                logger.error(f"Failed to decode message: {message['data']}")
                        elif message['type'] == 'subscribe':
                            # Subscription confirmed
                            logger.info("Subscribed to activity_feed:live")
                    
                    # Send heartbeat every 30 seconds
                    if time.time() - last_heartbeat > 30:
                        yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
                        last_heartbeat = time.time()
                        
            except GeneratorExit:
                pubsub.close()
                raise
            except Exception as e:
                logger.error(f"Error in SSE stream: {e}")
                pubsub.close()
                
        response = Response(
            generate(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive"
            }
        )
        response.implicit_sequence_conversion = False
        return response