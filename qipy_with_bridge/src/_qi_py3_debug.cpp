/*
 * Debug _qi.so - tests each step individually
 */
#include <Python.h>
#include <boost/python.hpp>
#include <dlfcn.h>
#include <cstdio>
#include <string>

int qi_test() { return 42; }

std::string qi_do_export() {
    typedef void (*export_fn)();

    void* handle = dlopen("libqipython3.so", RTLD_NOW | RTLD_GLOBAL);
    if (!handle) {
        return std::string("dlopen failed: ") + dlerror();
    }

    export_fn fn = (export_fn)dlsym(handle, "_ZN2qi2py10export_allEv");
    if (!fn) {
        return std::string("dlsym failed: ") + dlerror();
    }

    fprintf(stderr, "About to call export_all at %p\n", (void*)fn);
    fflush(stderr);

    try {
        fn();
        return "success";
    } catch (boost::python::error_already_set&) {
        PyErr_Print();
        return "boost::python::error_already_set";
    } catch (std::exception& e) {
        return std::string("exception: ") + e.what();
    }
}

BOOST_PYTHON_MODULE(_qi)
{
    boost::python::def("_test", &qi_test);
    boost::python::def("_do_export", &qi_do_export);
}
