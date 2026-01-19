"""
Django management command to test Redis connectivity.
Run with: python manage.py test_redis
"""
from django.core.management.base import BaseCommand
from django.conf import settings
import os


class Command(BaseCommand):
    help = 'Test Redis connectivity for Celery broker and result backend'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Show detailed Redis information',
        )

    def handle(self, *args, **options):
        verbose = options['verbose']
        
        self.stdout.write(self.style.HTTP_INFO('=' * 60))
        self.stdout.write(self.style.HTTP_INFO('Redis Connection Test'))
        self.stdout.write(self.style.HTTP_INFO('=' * 60))
        
        try:
            import redis
        except ImportError:
            self.stdout.write(
                self.style.ERROR('✗ redis package not installed')
            )
            self.stdout.write('  Install with: pip install redis')
            return
        
        redis_host = os.environ.get('REDIS_HOST', 'localhost')
        redis_port = int(os.environ.get('REDIS_PORT', '6379'))
        
        all_ok = True
        
        # Test broker connection (db=0)
        all_ok &= self._test_redis_db(
            redis, redis_host, redis_port, 0, 'Broker', verbose
        )
        
        # Test result backend connection (db=1)
        all_ok &= self._test_redis_db(
            redis, redis_host, redis_port, 1, 'Result Backend', verbose
        )
        
        # Test Celery configuration
        all_ok &= self._test_celery_config(verbose)
        
        self.stdout.write(self.style.HTTP_INFO('=' * 60))
        if all_ok:
            self.stdout.write(
                self.style.SUCCESS('✓ All Redis tests passed!')
            )
        else:
            self.stdout.write(
                self.style.ERROR('✗ Some tests failed')
            )
        self.stdout.write(self.style.HTTP_INFO('=' * 60))

    def _test_redis_db(
        self, 
        redis, 
        host: str, 
        port: int, 
        db: int, 
        name: str, 
        verbose: bool
    ) -> bool:
        """Test connection to a specific Redis database."""
        try:
            self.stdout.write(f'\nTesting {name} (db={db})...')
            
            client = redis.Redis(
                host=host,
                port=port,
                db=db,
                socket_connect_timeout=5
            )
            
            # Test ping
            if client.ping():
                self.stdout.write(
                    self.style.SUCCESS(f'  ✓ Connection OK ({host}:{port})')
                )
            
            # Test read/write
            test_key = f'test:django:management:{db}'
            client.set(test_key, 'working', ex=10)
            value = client.get(test_key)
            
            if value == b'working':
                self.stdout.write(
                    self.style.SUCCESS('  ✓ Read/write operations OK')
                )
                client.delete(test_key)
            
            if verbose:
                info = client.info('server')
                self.stdout.write(
                    f"  Redis version: {info.get('redis_version', 'unknown')}"
                )
                self.stdout.write(
                    f"  Uptime: {info.get('uptime_in_seconds', 0)} seconds"
                )
                
                stats = client.info('stats')
                self.stdout.write(
                    f"  Total connections: {stats.get('total_connections_received', 0)}"
                )
            
            return True
            
        except redis.ConnectionError as e:
            self.stdout.write(
                self.style.ERROR(f'  ✗ Connection failed: {e}')
            )
            self.stdout.write(
                f'  Make sure Redis is running on {host}:{port}'
            )
            return False
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'  ✗ Test failed: {e}')
            )
            return False

    def _test_celery_config(self, verbose: bool) -> bool:
        """Test Celery configuration."""
        try:
            self.stdout.write('\nTesting Celery configuration...')
            
            from water_delivery.celery import app
            
            self.stdout.write(
                self.style.SUCCESS(f'  ✓ Broker URL: {app.conf.broker_url}')
            )
            self.stdout.write(
                self.style.SUCCESS(f'  ✓ Result backend: {app.conf.result_backend}')
            )
            
            if verbose:
                self.stdout.write(f'  Timezone: {app.conf.timezone}')
                self.stdout.write(f'  Task serializer: {app.conf.task_serializer}')
            
            return True
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'  ✗ Celery test failed: {e}')
            )
            return False
