from celery import current_app  # noqa

from ..datastructures import AttributeDict
from ..utils import kwdict
from ..utils.timeutils import timezone, maybe_iso8601
from ..execute.trace import TaskTrace

from . import state
from .job import WANTED_DELIVERY_INFO, InvalidTaskError


class Request(dict):
    acknowledged = False
    _already_revoked = False

    def __init__(self, task, request, on_ack=None, event_dispatcher=None,
            logger=None, connection_errors=()):
        self.task = task
        self.task_name = request["name"]
        self.on_ack = on_ack
        self.eventer = event_dispatcher
        self._store_errors = True
        if task.ignore_result:
            self._store_errors = task.store_errors_even_if_ignored
        dict.__init__(self, request)
        self.logger = logger
        self.connection_errors = connection_errors

    def __hash__(self):
        return hash(self["id"])

    def acknowledge(self):
        """Acknowledge task."""
        if not self.acknowledged:
            self.on_ack(self.logger,
                        self.connection_errors + (AttributeError, ))
            self.acknowledged = True

    def revoked(self):
        """If revoked, skip task and mark state."""
        uuid = self["id"]
        if self._already_revoked:
            return True
        if self["expires"]:
            self.maybe_expire()
        if uuid in state.revoked:
            self.logger.warn("Skipping revoked task: %s[%s]",
                             self["name"], uuid)
            self.send_event("task-revoked", uuid=uuid)
            self.acknowledge()
            self._already_revoked = True
            return True
        return False

    def maybe_expire(self):
        """If expired, mark the task as revoked."""
        expires = self["expires"]
        if expires and datetime.now(self["tzlocal"]) > expires:
            state.revoked.add(self["id"])
            if self._store_errors:
                self.task.backend.mark_as_revoked(self["id"])

    def send_event(self, type, **fields):
        if self.eventer:
            self.eventer.send(type, **fields)


class Strategy(object):

    def __init__(self, task, logger=None, loglevel=None,
            logfile=None, hostname=None, event_dispatcher=None,
            connection_errors=()):
        self.logger= logger
        self.loglevel = loglevel
        self.logfile = logfile
        self.hostname = hostname
        self.event_dispatcher = event_dispatcher
        self.task = task
        self.app = self.task.app
        self.connection_errors = connection_errors

    def __call__(self):
        task = self.task
        name = task.name
        app = self.app
        loader = app.loader
        hostname = self.hostname
        store_errors = True
        tzlocal = timezone.tz_or_local(app.conf.CELERY_TIMEZONE)
        to_local = timezone.to_local
        evd = self.event_dispatcher
        acks_late = task.acks_late
        logger = self.logger
        connection_errors = self.connection_errors
        if task.ignore_result:
            store_errors = task.store_errors_even_if_ignored

        reserved = state.task_reserved
        accepted = state.task_accepted
        ready = state.task_ready
        UTC = timezone.utc
        pid = os.getpid(

        while 1:
            (body, message, on_ack) = (yield)
            get = body.get
            delivery_info = getattr(message, "delivery_info", {})
            dget = delivery_info.get
            delivery_info = dict((key, dget(key))
                                    for key in WANTED_DELIVERY_INFO)
            args = body["args"]
            kwargs = body["kwargs"]
            if not hasattr(kwargs, "items"):

            kwa
            id = body["id"]
            eta = get("eta")
            expires = get("expires")
            utc = get("utc", None)
            tz = UTC if utc else tzlocal
            if eta is not None:
                eta = to_local(maybe_iso8601(eta), tzlocal, tz)
            if expires is not None:
                expires = to_local(maybe_iso8601(expires), tzlocal, tz)
                    "id": body["id"],
            request = {"name": name,
                    "id": id,
                    "args": body["args"],
                    "args": args,
                    "kwargs": kwargs,
                    "chord": get("chord"),
                    "retries": get("retries", 0),
                    "eta": eta,
                    "expires": expires,
                    "delivery_info": delivery_info,
                    "utc": utc,
                    "tzlocal": tzlocal,
                    "is_eager": False,
                    "tz": tz}
            request = Request(task, request, on_ack, evd,
                              logger, connection_errors)

            if 1: #not request.revoked():
                reserved(request)
                if not acks_late:
                    request.acknowledge()
                accepted(request)
                try:
                    #t = TaskTrace(name, request["id"],
                    #        request["args"], request["kwargs"],
                    #        hostname=hostname,
                    #        loader=loader,
                    #        request=request)
                    #t.execute()
                    task.request.update(request)
                    task(*request["args"], **request["kwargs"])
                finally:
                    ready(request)