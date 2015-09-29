import random
import uuid
from itertools import count, cycle
from collections import Iterable, defaultdict

from tornado import gen
from tornado.gen import Return
from tornado.ioloop import IOLoop

from toolz import merge, concat, groupby

from .core import rpc


no_default = '__no_default__'


@gen.coroutine
def gather_from_center(stream, needed=[]):
    """ gather data from peers """
    needed = [n.key if isinstance(n, RemoteData) else n for n in needed]
    who_has = yield rpc(stream).who_has(keys=needed)
    assert set(who_has) == set(needed)

    result = yield gather_from_workers(who_has)
    raise Return([result[key] for key in needed])


@gen.coroutine
def gather_from_workers(who_has):
    """ gather data from peers """
    d = defaultdict(list)
    for key, addresses in who_has.items():
        try:
            addr = random.choice(list(addresses))
        except IndexError:
            raise KeyError('No workers found that have key: %s' % key)
        d[addr].append(key)

    results = yield [rpc(*addr).get_data(keys=keys)
                        for addr, keys in d.items()]

    # TODO: make resilient to missing workers
    raise Return(merge(results))


class RemoteData(object):
    """ Data living on a remote worker

    This is created by ``PendingComputation.get()`` which is in turn created by
    ``Pool.apply_async()``.  One can retrive the data from the remote worker by
    calling the ``.get()`` method on this object

    Example
    -------

    >>> pc = pool.apply_async(func, args, kwargs)  # doctest: +SKIP
    >>> rd = pc.get()  # doctest: +SKIP
    >>> rd.get()  # doctest: +SKIP
    10
    """
    def __init__(self, key, center_ip, center_port, status=None,
                       result=no_default):
        self.key = key
        self.status = status
        self.center_ip = center_ip
        self.center_port = center_port
        self._result = result

    def __str__(self):
        if len(self.key) > 13:
            key = self.key[:10] + '...'
        else:
            key = self.key
        return "RemoteData<center=%s:%d, key=%s>" % (self.center_ip,
                self.center_port, key)

    __repr__ = __str__

    @gen.coroutine
    def _get(self, raiseit=True):
        who_has = yield rpc(self.center_ip, self.center_port).who_has(
                keys=[self.key], close=True)
        ip, port = random.choice(list(who_has[self.key]))
        result = yield rpc(ip, port).get_data(keys=[self.key], close=True)

        self._result = result[self.key]

        if raiseit and self.status == b'error':
            raise self._result
        else:
            raise Return(self._result)

    def get(self):
        if self._result is not no_default:
            return self._result
        else:
            result = IOLoop.current().run_sync(lambda: self._get(raiseit=False))
            if self.status == b'error':
                raise result
            else:
                return result

    @gen.coroutine
    def _delete(self):
        yield rpc(self.center_ip, self.center_port).delete_data(
                keys=[self.key])

    """
    def delete(self):
        sync(self._delete(), self.loop)
    """

@gen.coroutine
def scatter_to_center(ip, port, data, key=None):
    """ Scatter data to workers

    See also:
        scatter_to_workers
    """
    ncores = yield rpc(ip, port).ncores()

    result = yield scatter_to_workers(ip, port, ncores, data, key=key)
    raise Return(result)


@gen.coroutine
def scatter_to_workers(ip, port, ncores, data, key=None):
    """ Scatter data directly to workers

    This distributes data in a round-robin fashion to a set of workers based on
    how many cores they have.

    See also:
        scatter_to_center: check in with center first to find workers
    """
    if key is None:
        key = str(uuid.uuid1())

    if isinstance(ncores, Iterable) and not isinstance(ncores, dict):
        ncores = {worker: 1 for worker in ncores}

    workers = list(concat([w] * nc for w, nc in ncores.items()))
    names = ('%s-%d' % (key, i) for i in count(0))

    L = list(zip(cycle(workers), names, data))
    d = groupby(0, L)
    d = {k: {b: c for a, b, c in v}
          for k, v in d.items()}

    yield [rpc(*w).update_data(data=v) for w, v in d.items()]

    result = [RemoteData(b, ip, port, result=c)
                for a, b, c in L]

    raise Return(result)


def unpack_remotedata(o):
    """ Unpack RemoteData objects from collection

    Returns original collection and set of all found keys

    >>> rd = RemoteData('mykey', '127.0.0.1', 8787)
    >>> unpack_remotedata(1)
    (1, set())
    >>> unpack_remotedata(rd)
    ('mykey', {'mykey'})
    >>> unpack_remotedata([1, rd])
    ([1, 'mykey'], {'mykey'})
    >>> unpack_remotedata({1: rd})
    ({1: 'mykey'}, {'mykey'})
    >>> unpack_remotedata({1: [rd]})
    ({1: ['mykey']}, {'mykey'})
    """
    if isinstance(o, RemoteData):
        return o.key, {o.key}
    elif isinstance(o, (tuple, list, set, frozenset)):
        out, sets = zip(*map(unpack_remotedata, o))
        return type(o)(out), set.union(*sets)
    elif isinstance(o, dict):
        if o:
            values, sets = zip(*map(unpack_remotedata, o.values()))
            return dict(zip(o.keys(), values)), set.union(*sets)
        else:
            return dict(), set()
    else:
        return o, set()
