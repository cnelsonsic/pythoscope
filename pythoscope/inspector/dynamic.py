import os
import sys

from pythoscope.tracer import ICallback, Tracer


class CallStack(object):
    def __init__(self):
        self.last_traceback = None
        self.stack = []
        self.top_level_calls = []
        self.top_level_side_effects = [] # TODO use this list for creating global setup & teardown methods

    def called(self, call):
        if self.stack:
            self.stack[-1].add_subcall(call)
        else:
            self.top_level_calls.append(call)
        self.stack.append(call)

    def returned(self, output):
        if self.stack:
            caller = self.stack.pop()
            caller.set_output(output)

            # If the last exception is reported by sys.exc_info() it means
            # it was handled inside the returning call.
            handled_traceback = sys.exc_info()[2]
            if handled_traceback is self.last_traceback:
                caller.clear_exception()

    def raised(self, exception, traceback):
        if self.stack:
            caller = self.stack[-1]
            caller.set_exception(exception)
            self.last_traceback = traceback

    def side_effect(self, side_effect):
        if self.stack:
            self.stack[-1].add_side_effect(side_effect)
        else:
            self.top_level_side_effects.append(side_effect)

    def unwind(self, value):
        while self.stack:
            self.returned(value)

class Inspector(ICallback):
    """Controller of the dynamic inspection process. It receives information
    from the tracer and propagates it to Execution and CallStack objects.
    """
    def __init__(self, execution):
        self.execution = execution
        self.call_stack = CallStack()

    def finalize(self):
        # TODO: There are ways for the application to terminate (easiest
        # being os._exit) without unwinding the stack. This means Pythoscope
        # will be left with some calls registered on the stack without a return.
        # We remedy the situation by injecting None as the return value for
        # those calls. In the future we should also associate some kind of
        # an "exit" side effect with those calls.
        self.call_stack.unwind(self.execution.serialize(None))

        # Copy the call graph structure to the Execution instance.
        self.execution.call_graph = self.call_stack.top_level_calls
        self.execution.finalize()

    def method_called(self, name, obj, args, code, frame):
        call = self.execution.create_method_call(name, obj, args, code, frame)
        return self.called(call)

    def function_called(self, name, args, code, frame):
        call = self.execution.create_function_call(name, args, code, frame)
        return self.called(call)

    def returned(self, output):
        self.call_stack.returned(self.execution.serialize(output))

    def raised(self, exception, traceback):
        self.call_stack.raised(self.execution.serialize(exception), traceback)

    def side_effect(self, klass, *args):
        self.call_stack.side_effect(self.execution.create_side_effect(klass, *args))

    def called(self, call):
        if call:
            self.call_stack.called(call)
            return True

def inspect_point_of_entry(point_of_entry):
    projects_root = point_of_entry.project.path
    point_of_entry.clear_previous_run()

    # Put project's path into PYTHONPATH, so point of entry's imports work.
    sys.path.insert(0, projects_root)
    # Change current directory to the project's root, so the POE code can use
    # relative paths for reading project data files.
    old_cwd = os.getcwd()
    os.chdir(projects_root)

    try:
        inspect_code_in_context(point_of_entry.get_content(),
                                point_of_entry.execution)
    finally:
        sys.path.remove(projects_root)
        os.chdir(old_cwd)

# :: (str, Execution) -> None
def inspect_code_in_context(code, execution):
    """Inspect given piece of code in the context of given Execution instance.

    May raise exceptions.
    """
    inspector = Inspector(execution)
    tracer = Tracer(inspector)
    try:
        tracer.trace(code)
    finally:
        inspector.finalize()
