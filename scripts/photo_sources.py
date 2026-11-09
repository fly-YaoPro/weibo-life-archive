"""Read-only intake for a user-selected export folder or bounded photo ZIP.

This is not a native Photos database reader or cloud download client. Native
libraries must first be exported by an authorized host connector or the user.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import tempfile
import unicodedata
import zipfile


HEIF = {'.heic', '.heif'}
NATIVE_LIBRARY_SUFFIXES = {'.photoslibrary', '.photolibrary'}
PLACEHOLDER_SUFFIXES = {'.icloud', '.cloud'}
MAX_ZIP_ENTRIES = 50_000
MAX_ZIP_BYTES = 10 * 1024 ** 3
MAX_ZIP_MEMBER_BYTES = 1024 ** 3
MAX_ZIP_RATIO = 200
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}


@dataclass(frozen=True)
class PhotoSource:
    root: Path
    original: Path
    kind: str


def native_library_path(path):
    """Detect the selected library and paths inside one without opening it."""
    return any(part.lower().endswith(tuple(NATIVE_LIBRARY_SUFFIXES)) for part in Path(path).parts)


def is_placeholder(path):
    """Only known stub markers/OS attributes; absence does not prove hydration."""
    path = Path(path)
    if path.suffix.lower() in PLACEHOLDER_SUFFIXES:
        return True
    attributes = getattr(path.stat(), 'st_file_attributes', 0)
    return bool(attributes & (0x1000 | 0x40000 | 0x400000))


def _member_path(info):
    # orig_filename retains NUL/backslash bytes that ZipInfo can normalize or
    # truncate differently by OS. Validate the original member name first.
    value = info.orig_filename
    if not value or '\\' in value or ':' in value or any(ord(char) < 32 for char in value):
        raise ValueError('unsafe_zip_path: ZIP仅接受可移植的相对文件路径')
    raw_parts = value.rstrip('/').split('/')
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or any(part in {'', '.', '..'} for part in raw_parts):
        raise ValueError('unsafe_zip_path: ZIP路径越界或含空目录段')
    for part in raw_parts:
        if part.rstrip(' .') != part or part.split('.')[0].upper() in _RESERVED or len(part) > 240:
            raise ValueError('unsafe_zip_path: ZIP含系统保留或不可移植名称')
    if native_library_path(path):
        raise ValueError('native_photo_library_requires_export: 不读取相册资料库；请导出选定原片后重试')
    mode = info.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if kind and kind not in {stat.S_IFREG, stat.S_IFDIR}:
        raise ValueError('unsafe_zip_link_or_special_file: ZIP不能包含链接或特殊文件')
    if info.external_attr & 0x400:
        raise ValueError('unsafe_zip_reparse_point: ZIP不能包含重解析点')
    if info.flag_bits & 1:
        raise ValueError('encrypted_photo_zip_unsupported: 请由用户正常解密并导出照片，不读取密码')
    return Path(*raw_parts)


def _extract_zip(archive, destination, *, max_entries=MAX_ZIP_ENTRIES,
                 max_bytes=MAX_ZIP_BYTES, max_member_bytes=MAX_ZIP_MEMBER_BYTES,
                 max_ratio=MAX_ZIP_RATIO):
    """Validate every member before writing, then stream with actual-size limits."""
    with zipfile.ZipFile(archive) as zipped:
        members = zipped.infolist()
        if len(members) > max_entries:
            raise ValueError('photo_zip_limit: ZIP条目过多，请分批导出所选相册')
        seen, validated, total = set(), [], 0
        for info in members:
            relative = _member_path(info)
            key = unicodedata.normalize('NFC', relative.as_posix()).casefold()
            if key in seen:
                raise ValueError('unsafe_zip_duplicate_path: ZIP含重复或大小写冲突路径')
            seen.add(key)
            if info.is_dir():
                validated.append((info, relative))
                continue
            total += info.file_size
            if info.file_size > max_member_bytes or total > max_bytes or info.file_size > max(1, info.compress_size) * max_ratio:
                raise ValueError('photo_zip_limit: ZIP展开体积或压缩比超出安全范围，请分批导出')
            validated.append((info, relative))
        actual_total = 0
        for info, relative in validated:
            target = destination / relative
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            actual_member = 0
            with zipped.open(info) as incoming, target.open('xb') as outgoing:
                while True:
                    chunk = incoming.read(1024 * 1024)
                    if not chunk:
                        break
                    actual_member += len(chunk)
                    actual_total += len(chunk)
                    if actual_member > max_member_bytes or actual_total > max_bytes or actual_member > info.file_size:
                        raise ValueError('photo_zip_limit: ZIP实际展开体积超出声明或安全范围')
                    outgoing.write(chunk)
            if actual_member != info.file_size:
                raise ValueError('photo_zip_size_mismatch: ZIP成员不完整')


@contextmanager
def prepare_photo_source(source, output):
    """Yield a selected export only; ZIP extraction is disposable and private."""
    output_path = Path(output).absolute()
    if native_library_path(output_path) or native_library_path(output_path.resolve()):
        raise ValueError('native_photo_library_output_forbidden: 成册项目不能写入系统相册资料库，请使用独立工作目录')
    selected = Path(source).absolute()
    if selected.is_symlink():
        raise ValueError('source不能是符号链接目录或文件')
    if native_library_path(selected):
        raise ValueError('native_photo_library_requires_export: 不直接读取系统相册资料库；请用已授权连接器只读导出所选相册，或在相册中导出未修改的原片到独立目录/ZIP')
    selected = selected.resolve(strict=True)
    if native_library_path(selected):
        raise ValueError('native_photo_library_requires_export: 资料库内部路径不可用，请先导出选定原片')
    if selected.is_dir():
        yield PhotoSource(selected, selected, 'exported_photo_folder')
        return
    if selected.suffix.lower() != '.zip' or not selected.is_file():
        raise ValueError('photo_source_requires_export: 请选择已导出的照片目录或ZIP；不读取Photos/iCloud/Windows相册数据库，不自动扫描整机')
    output = Path(output).absolute()
    output = output.parent.resolve(strict=True) / output.name
    if output == selected or selected.is_relative_to(output):
        raise ValueError('source与output必须分离，不能互相包含')
    if is_placeholder(selected):
        raise ValueError('cloud_placeholder_requires_download: 所选ZIP尚未完整下载，请先在原平台完成下载')
    with tempfile.TemporaryDirectory(prefix='.photo-export-') as scratch:
        extracted = Path(scratch)
        _extract_zip(selected, extracted)
        yield PhotoSource(extracted, selected, 'exported_photo_zip')
