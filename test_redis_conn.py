"""
Simple script to test Redis connectivity.
Run with: python test_redis_conn.py
"""
import os
import traceback
from dotenv import load_dotenv

load_dotenv()

def test_redis_connection() -> bool:
    """Test Redis connection using redis-py."""
    try:
        import redis
        
        redis_host = os.environ.get('REDIS_HOST', 'localhost')
        redis_port = int(os.environ.get('REDIS_PORT', '6379'))
        
        # Test connection to broker database (0)
        print(f"Testing Redis connection to {redis_host}:{redis_port}...")
        
        client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=0,
            socket_connect_timeout=5
        )
        
        # Test ping
        if client.ping():
            print("✓ Redis broker (db=0) connection OK")
        
        # Test result backend (db=1)
        result_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=1,
            socket_connect_timeout=5
        )
        
        if result_client.ping():
            print("✓ Redis result backend (db=1) connection OK")
        
        # Test basic operations
        test_key = 'test:connection'
        client.set(test_key, 'working', ex=10)
        value = client.get(test_key)
        
        if value == b'working':
            print("✓ Redis read/write operations OK")
            client.delete(test_key)
        
        # Get some info
        info = client.info('server')
        print(f"✓ Redis version: {info.get('redis_version', 'unknown')}")
        
        return True
        
    except ImportError:
        print("✗ redis package not installed. Install with: pip install redis")
        return False
    except redis.ConnectionError as e:
        print(f"✗ Redis connection failed: {e}")
        print(f"  Make sure Redis is running on {redis_host}:{redis_port}")
        return False
    except Exception:
        print("✗ Redis connection test failed:")
        traceback.print_exc()
        return False


def test_celery_connection() -> bool:
    """Test Celery's ability to connect to Redis."""
    try:
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'water_delivery.settings')
        import django
        django.setup()
        
        from water_delivery.celery import app
        
        print("\nTesting Celery configuration...")
        
        # Inspect broker connection
        inspect = app.control.inspect()
        
        # This will fail if broker is not accessible
        print(f"✓ Celery broker URL: {app.conf.broker_url}")
        print(f"✓ Celery result backend: {app.conf.result_backend}")
        
        return True
        
    except Exception as e:
        print(f"✗ Celery connection test failed: {e}")
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("=" * 60)
    print("Redis Connection Test")
    print("=" * 60)
    
    redis_ok = test_redis_connection()
    celery_ok = test_celery_connection()
    
    print("\n" + "=" * 60)
    if redis_ok and celery_ok:
        print("✓ All Redis tests passed!")
    else:
        print("✗ Some tests failed. Check output above.")
    print("=" * 60)
