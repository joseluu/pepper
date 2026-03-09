/*
 * Minimal _qi.so bootstrap for Python 3
 *
 * This is a pure C wrapper that avoids boost::python headers entirely.
 * It uses dlopen/dlsym to call qi::py::export_all() from libqipython3.so
 *
 * Compile with:
 *   gcc -m32 -shared -fPIC -o _qi.so _qi_py3_minimal.c -ldl -lpython3.5m
 */

#include <Python.h>
#include <dlfcn.h>
#include <stdio.h>

/* Module definition for Python 3 */
static struct PyModuleDef qi_module = {
    PyModuleDef_HEAD_INIT,
    "_qi",                          /* module name */
    "QI messaging Python bindings", /* docstring */
    -1,                             /* size of per-interpreter state */
    NULL,                           /* methods */
    NULL, NULL, NULL, NULL
};

/* Function pointer type for qi::py::export_all */
typedef void (*export_all_fn)(void);

PyMODINIT_FUNC PyInit__qi(void)
{
    void *handle;
    export_all_fn export_all;

    /* Initialize Python threading */
    PyEval_InitThreads();

    /* Load libqipython3.so */
    handle = dlopen("libqipython3.so", RTLD_NOW | RTLD_GLOBAL);
    if (!handle) {
        PyErr_Format(PyExc_ImportError,
            "Cannot load libqipython3.so: %s", dlerror());
        return NULL;
    }

    /* Get qi::py::export_all symbol
     * Mangled name: _ZN2qi2py10export_allEv
     */
    export_all = (export_all_fn)dlsym(handle, "_ZN2qi2py10export_allEv");
    if (!export_all) {
        PyErr_Format(PyExc_ImportError,
            "Cannot find qi::py::export_all: %s", dlerror());
        dlclose(handle);
        return NULL;
    }

    /* Create the module first */
    PyObject *module = PyModule_Create(&qi_module);
    if (!module) {
        dlclose(handle);
        return NULL;
    }

    /* Now call export_all to register all the classes
     * Note: This relies on export_all() using the current interpreter
     * and adding to the module that's being initialized
     */
    export_all();

    return module;
}
