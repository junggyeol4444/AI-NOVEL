"""Background real GGUF scene worker; never touches QWidget or SQLite."""
from PySide6.QtCore import QThread, Signal
from ai_novel_factory.local_models import LocalModelError, draft_scene


class DraftWorker(QThread):
    generated = Signal(object)
    failed = Signal(str)

    def __init__(self, request, provider, parent=None):
        super().__init__(parent)
        self._request = request
        self._provider = provider

    def run(self):
        try:
            self.generated.emit(draft_scene(self._request, self._provider))
        except LocalModelError as exc:
            reason = str(exc)
            self.failed.emit(reason if reason in ('native_timeout', 'native_inference_failure')
                             else 'LocalModelError')
        except (ValueError, OSError) as exc:
            self.failed.emit(type(exc).__name__)
        except BaseException:
            self.failed.emit('UnknownError')
