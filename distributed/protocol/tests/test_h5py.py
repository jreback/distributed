import pytest

h5py = pytest.importorskip('h5py')

from distributed.protocol import serialize, deserialize, dumps, loads

from distributed.utils import tmpfile


def test_serialize_deserialize_file():
    with tmpfile() as fn:
        with h5py.File(fn, mode='a') as f:
            f.create_dataset('/x', shape=(2, 2), dtype='i4')
        with h5py.File(fn, mode='r') as f:
            g = deserialize(*serialize(f))
            assert f.filename == g.filename
            assert isinstance(g, h5py.File)
            assert f.mode == g.mode

            assert g['x'].shape == (2, 2)


def test_serialize_deserialize_group():
    with tmpfile() as fn:
        with h5py.File(fn, mode='a') as f:
            f.create_dataset('/group1/group2/x', shape=(2, 2), dtype='i4')
        with h5py.File(fn, mode='r') as f:
            group = f['/group1/group2']
            group2 = deserialize(*serialize(group))

            assert isinstance(group2, h5py.Group)
            assert group.file.filename == group2.file.filename

            assert group2['x'].shape == (2, 2)


def test_serialize_deserialize_dataset():
    with tmpfile() as fn:
        with h5py.File(fn, mode='a') as f:
            x = f.create_dataset('/group1/group2/x', shape=(2, 2), dtype='i4')
        with h5py.File(fn, mode='r') as f:
            x = f['group1/group2/x']
            y = deserialize(*serialize(x))
            assert isinstance(y, h5py.Dataset)
            assert x.name == y.name
            assert x.file.filename == y.file.filename
            assert (x[:] == y[:]).all()


def test_raise_error_on_serialize_write_permissions():
    with tmpfile() as fn:
        with h5py.File(fn, mode='a') as f:
            x = f.create_dataset('/x', shape=(2, 2), dtype='i4')
            f.flush()
            with pytest.raises(ValueError):
                serialize(x)
            with pytest.raises(ValueError):
                serialize(f)


from distributed.utils_test import gen_cluster
from distributed.client import _wait

from tornado import gen

import dask.array as da

@gen_cluster(client=True)
def test_h5py_serialize(c, s, a, b):
    with tmpfile() as fn:
        with h5py.File(fn, mode='a') as f:
            x = f.create_dataset('/group/x', shape=(4,), dtype='i4',
                                 chunks=(2,))
            x[:] = [1, 2, 3, 4]
            f.flush()
        with h5py.File(fn, mode='r') as f:
            dset = f['/group/x']
            x = da.from_array(dset, chunks=dset.chunks)
            y = c.compute(x)
            y = yield y._result()
            assert (y[:] == dset[:]).all()