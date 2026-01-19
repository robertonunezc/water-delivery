from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    # No automatic signal imports: employee creation should be explicit via Employee admin

    def ready(self) -> None:
        """Run when Django app is ready - test Redis connectivity."""
        import os
        
        # Only run checks if not in migration or other management commands
        # that don't need Redis
        import sys
        if 'migrate' in sys.argv or 'makemigrations' in sys.argv:
            return
        
        try:
            import redis
            
            host = os.environ.get('REDIS_HOST', 'localhost')
            port = int(os.environ.get('REDIS_PORT', '6379'))
            password = os.environ.get('REDIS_PASSWORD', None)
            
            # Test broker connection (db=0)
            client = redis.Redis(
                host=host, 
                port=port, 
                db=0,
                password=password,
                socket_connect_timeout=2
            )
            client.ping()
            
            # Test result backend connection (db=1)
            result_client = redis.Redis(
                host=host, 
                port=port, 
                db=1,
                password=password,
                socket_connect_timeout=2
            )
            result_client.ping()
            
            logger.info(f"✓ Redis connection OK ({host}:{port})")
            
        except ImportError:
            logger.warning("⚠ redis package not installed - Celery tasks will not work")
        except redis.ConnectionError as e:
            logger.warning(f"⚠ Redis connection failed: {e}")
            logger.warning(f"  Celery tasks will not work. Check Redis at {host}:{port}")
        except redis.AuthenticationError as e:
            logger.warning(f"⚠ Redis authentication failed: {e}")
            logger.warning(f"  Set REDIS_PASSWORD environment variable")
        except Exception as e:
            logger.warning(f"⚠ Redis connection test error: {e}")
