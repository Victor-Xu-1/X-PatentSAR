"""Job-local exact-Molfile graph preparation, not a scientific result cache."""

from collections import OrderedDict

from .graphs import graph
from .molecules import read_molfile


class GraphPool:
    def __init__(self):
        self._graphs = OrderedDict()

    def read(self, molfile):
        if molfile not in self._graphs:
            self._graphs[molfile] = graph(read_molfile(molfile))
            if len(self._graphs) > 256:
                self._graphs.popitem(last=False)
        else:
            self._graphs.move_to_end(molfile)
        return self._graphs[molfile]
