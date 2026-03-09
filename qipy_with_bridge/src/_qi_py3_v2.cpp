/*
 * _qi.so bootstrap module for Python 3 - v2
 * Uses qi::py::initialize() instead of export_all()
 */

#include <Python.h>
#include <boost/python.hpp>

namespace qi {
    namespace py {
        void export_all();
        void initialize(bool);
        void initialise();
    }
    namespace log {
        void addCategory(const std::string& cat);
    }
}

BOOST_PYTHON_MODULE(_qi)
{
    PyEval_InitThreads();

    try {
        qi::py::initialize(false);
    } catch (boost::python::error_already_set&) {
        // Fetch and print the actual Python error
        PyErr_Print();
    } catch (std::exception& e) {
        PyErr_SetString(PyExc_ImportError, e.what());
    }
}
