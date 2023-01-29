from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils import timezone

from easy_thumbnails import utils, signal_handlers
from easy_thumbnails.conf import settings
from easy_thumbnails.version_utils import get_version


if settings.THUMBNAIL_CACHE:
    try:
        from django.core.cache import caches
        cache = caches[settings.THUMBNAIL_CACHE]
    except ImportError:
        raise ImproperlyConfigured(
            'You are trying to use the cache on a version of Django '
            'that does not support caching')
    except KeyError:
        raise ImproperlyConfigured(
            "The cache specified in `THUMBNAIL_CACHE` doesn't seem "
            "to exist")


class FileManager(models.Manager):

    def _get_cache_key(self, kwargs):
        version = get_version()
        return f"easy_thumbnails:{version}:FileManager:{kwargs['storage_hash']}:{kwargs['name']}"

    def _delete_cache_key(self, kwargs):
        cache_key = self._get_cache_key(kwargs)
        cache.delete(cache_key)

    def get_file(self, storage, name, create=False, update_modified=None,
                 check_cache_miss=False, **kwargs):
        kwargs.update(dict(storage_hash=utils.get_storage_hash(storage),
                           name=name))        
        cache_key = self._get_cache_key(kwargs)

        if create:
            if update_modified:
                defaults = kwargs.setdefault('defaults', {})
                defaults['modified'] = update_modified
            obj, created = self.get_or_create(**kwargs)
        else:
            created = False
            kwargs.pop('defaults', None)

            obj = None
            if settings.THUMBNAIL_CACHE and settings.THUMBNAIL_QUERYSET_CACHING:
                obj = cache.get(cache_key)
            if obj is None:
                try:
                    manager = self._get_thumbnail_manager()
                    obj = manager.get(**kwargs)
                except self.model.DoesNotExist:

                    if check_cache_miss and storage.exists(name):
                        # File already in storage, update cache. Using
                        # get_or_create again in case this was updated while
                        # storage.exists was running.
                        obj, created = self.get_or_create(**kwargs)
                    else:
                        return

                if settings.THUMBNAIL_CACHE and settings.THUMBNAIL_QUERYSET_CACHING:
                    cache.set(cache_key, obj, None)

        if update_modified and not created:
            if obj.modified != update_modified:
                self.filter(pk=obj.pk).update(modified=update_modified)

                if settings.THUMBNAIL_CACHE and settings.THUMBNAIL_QUERYSET_CACHING:
                    obj.modified = update_modified
                    cache.set(cache_key, obj, None)

        return obj

    def _get_thumbnail_manager(self):
        return self


class ThumbnailManager(FileManager):
    
    def _get_cache_key(self, kwargs):
        version = get_version()
        return f"easy_thumbnails:{version}:ThumbnailManager:{kwargs['storage_hash']}:{kwargs['name']}:{kwargs['source'].pk}"

    def _get_thumbnail_manager(self):
        if settings.THUMBNAIL_CACHE_DIMENSIONS:
            return self.select_related("dimensions")
        return self


class File(models.Model):
    storage_hash = models.CharField(max_length=40, db_index=True)
    name = models.CharField(max_length=255, db_index=True)
    modified = models.DateTimeField(default=timezone.now)

    objects = FileManager()

    class Meta:
        abstract = True
        unique_together = (('storage_hash', 'name'),)

    def __str__(self):
        return self.name


class Source(File):
    pass


class Thumbnail(File):
    source = models.ForeignKey(Source, related_name='thumbnails',
                               on_delete=models.CASCADE)

    objects = ThumbnailManager()

    class Meta:
        unique_together = (('storage_hash', 'name', 'source'),)


class ThumbnailDimensions(models.Model):
    thumbnail = models.OneToOneField(Thumbnail, related_name="dimensions",
                                     on_delete=models.CASCADE)
    width = models.PositiveIntegerField(null=True)
    height = models.PositiveIntegerField(null=True)

    def __str__(self):
        return "%sx%s" % (self.width, self.height)

    @property
    def size(self):
        return self.width, self.height


models.signals.pre_save.connect(signal_handlers.find_uncommitted_filefields)
models.signals.post_save.connect(signal_handlers.signal_committed_filefields)
