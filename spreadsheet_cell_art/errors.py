"""CLIでトレースバックや機密情報を表示せず扱う例外。"""


class ArtError(RuntimeError):
    pass


class CreationUnknown(ArtError):
    pass


class CreationRejected(ArtError):
    pass
