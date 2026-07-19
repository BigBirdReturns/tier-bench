from __future__ import annotations

from .desk_ui_markup import MARKUP
from .desk_ui_script import SCRIPT
from .desk_ui_style import STYLE

HTML = MARKUP.replace("__MONSTER_STYLE__", STYLE).replace("__MONSTER_SCRIPT__", SCRIPT)
