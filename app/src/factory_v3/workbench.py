"""Native engineering remains upstream-owned; cloud jobs cannot bypass v3 grants."""
from cim.workbench import FactoryWorkbench as NativeWorkbench

class FactoryWorkbench(NativeWorkbench):
    def start(self):
        super().start()
        if getattr(self,"factory_v3",None): self.factory_v3.runtime.start_worker()

    def close(self):
        if getattr(self,"factory_v3",None): self.factory_v3.runtime.close()
        return super().close()

    def submit(self,command):
        raise PermissionError("请从 v3 模块授权入口使用模型；原生工程不直接外发")

    def repair_generation(self,job_id,request_id):
        raise PermissionError("请从 v3 模块授权入口处理候选返修")
