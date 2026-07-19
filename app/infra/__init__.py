"""Infrastructure backends behind interfaces: Cache, TaskQueue, EventBus.

Default backends are in-memory / in-process (single-process mode); Redis backends
unlock multiple API replicas + a separate worker. Selected by config; only this
package imports ``redis`` / ``arq``. Built in P1 (see PLAN.md).
"""
