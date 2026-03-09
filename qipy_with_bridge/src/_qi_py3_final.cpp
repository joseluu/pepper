/*
 * _qi.so for Python 3 - NAOqi 2.7
 * Calls export_all() from libqipython3.so within BOOST_PYTHON_MODULE scope
 */
#include <Python.h>
#include <boost/python.hpp>
#include <dlfcn.h>

typedef void (*export_fn)();

BOOST_PYTHON_MODULE(_qi)
{
    PyEval_InitThreads();

    void* handle = dlopen("libqipython3.so", RTLD_NOW | RTLD_GLOBAL);
    if (!handle) {
        PyErr_Format(PyExc_ImportError, "Cannot load libqipython3.so: %s", dlerror());
        boost::python::throw_error_already_set();
    }

    export_fn fn = (export_fn)dlsym(handle, "_ZN2qi2py10export_allEv");
    if (!fn) {
        PyErr_Format(PyExc_ImportError, "Cannot find export_all: %s", dlerror());
        boost::python::throw_error_already_set();
    }

    // Check that scope is valid
    boost::python::scope current;
    fprintf(stderr, "scope ptr: %p, scope is None: %d\n",
            current.ptr(), current.ptr() == Py_None);
    fflush(stderr);

    try {
        fn();
    } catch (boost::python::error_already_set&) {
        PyErr_Print();
        fprintf(stderr, "export_all raised Python exception (see above)\n");
        fflush(stderr);
    }
}
