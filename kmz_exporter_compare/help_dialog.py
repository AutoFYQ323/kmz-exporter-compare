# -*- coding: utf-8 -*-
"""Help text. Each string is a translation key."""

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QTabWidget, QTextBrowser, QVBoxLayout

from .i18n import localize_button_box, tr
from .qtutil import apply_taskbar_window, run_dialog

PAGES = (
    ("快速开始", "<p><b>五件事</b></p><p>主页是五个功能按钮。导出 KMZ 按图层组写出 KMZ 或 KML，点图标和分类颜色与 QGIS 地图上的符号一致。手动样式用于文件夹名对不上时先配对再套图标。自动样式用于文件夹名一致时套参考样式。坐标对比把左侧图层和工程图层按容差比较，距离用工程坐标系。图层对比比较要素数量与 Name、图层名称与字段（含顺序），或点线面。</p><p><b>注意</b></p><p>本窗口独立出现在系统任务栏，可单独最小化；QGIS 最小化后仍可拖入 KMZ。坐标对比不列出无几何的文件夹图层；底部「空图层」可隐藏要素数为 0 的图层，默认显示。结果图层放在「KMZ对比」组，几何已转到工程坐标系。清空数据、打开编辑、复制图层等图层面板快捷操作请用 Layers Panel Tools 插件。语言菜单会切换主页和各功能页上的按钮、标题和提示。第一次打开跟随 QGIS 的界面语言（English、中文、Español、Français、العربية、Italiano、Deutsch、日本語、한국어），其它非九种之一、或 QGIS 与系统语言都读不到时，默认英文。非中文界面下，译文未命中时亦回退英文。语言名称在菜单里始终用各自的写法。手动切换后会记住，之后不再跟着 QGIS 变。</p>"),
    ("导出 KMZ", "<p><b>做什么</b></p><p>按当前工程的图层组写出 KMZ 或 KML。点图标、分类颜色和 QGIS 地图上的符号一致：单一符号、分类、分级都按地图上的样子导出。可以改每个图层的导出名称、显示字段，按 QGIS 分类或字段拆子文件夹，并挑选要写出的字段。</p><p><b>怎么用</b></p><p>这一页就是主窗口换过的布局。勾选要导出的图层。下面没有矢量图层的文件夹也会列出，勾选后写成没有要素的文件夹；要素数为 0 的图层仍由「导出空图层」决定。需要时点「字段」挑选字段。共用字段可以把各图层里只差大小写的字段收成同一个。勾选和路径的导入、导出在主页工具栏，不在这一页。底部按钮顺序为全选/全不选、返回主页面、保存配置、导出KMZ。最后点「导出KMZ」，在保存窗口里选 KMZ 或 KML。点「返回主页面」或按 Esc 回到主页。成功与失败说明随界面语言；无法对应九种语言之一（含 QGIS 与系统语言都读不到）时，界面与结果句默认英文。</p>"),
    ("手动样式", "<p><b>做什么</b></p><p>被替换 KMZ 和参考 KMZ 的文件夹名对不上时用。先配对，再把参考文件的图标和气泡套到被替换数据上。默认按参考的文件夹结构和名称输出，几何和属性仍来自被替换文件。</p><p><b>怎么用</b></p><p>把两个 KMZ 拖进虚线框，或点「选择被替换图层」「选择参考图层」。被替换图层提供几何和属性；参考图层提供图标和气泡样式。点「执行替换」后弹出匹配页。匹配页一行里是自动匹配、保存配置和「导出KMZ/KML」，点保存配置才记住这些选项。配成空的不套用。确定后选择输出，可以是 KMZ 或 KML，不能和被替换文件、参考文件是同一个。点「返回主页面」或按 Esc 回到主页。</p>"),
    ("自动样式", "<p><b>做什么</b></p><p>文件夹名一致时，用参考 KMZ 的图标和气泡替换被替换 KMZ 的样式。几何和属性仍来自被替换文件。</p><p><b>怎么用</b></p><p>拖入或选择被替换图层、参考图层。被替换图层提供几何和属性；参考图层提供图标和气泡样式。点「执行替换并导出（输出图层）」，选择一个新的 KMZ 或 KML 作为输出。结果窗口里绿色表示已替换，红色表示没套上。点「返回主页面」或按 Esc 回到主页。</p>"),
    ("坐标对比", "<p><b>做什么</b></p><p>把左侧图层和当前工程图层按容差比较。可以只要重叠部分，或只要不重叠部分。结果写成新的内存图层。</p><p><b>怎么用</b></p><p>左上角可以切到「导入 KML / KMZ」，也可以切到「在 QGIS 选择」。右边框里是对比类型、容差（括号里是当前工程坐标系的单位，比如米或度）、保存编辑模式和三个按钮（返回主页面、保存配置、批量运行对比），两边这一列一样高。距离在工程坐标系里计算后再和容差比。勾选「保存编辑模式」时，只会保存并退出<strong>已配对</strong>图层的编辑，不会动未参与配对的图层。点、线、面、刷新图层在下面第一行；自动匹配、已匹配、未匹配、清空配对、空图层在第二行。筛选两边一起生效。刷新图层会按当前工程重列图层。左边一次选一个图层，按住拖到右边同一类型的行上。配上以后，右边名称后面会出现红色加粗的 VS 和左边图层，行尾的 × 可以拆开这次配对。已配对的两边都标绿。自动匹配优先整名完全一致，再按名称里的关键词配对，不要求整名一致，也不分大小写。换左侧 KML/KMZ 文件时会清空已有配对。容差默认 0.00001，单位跟着工程坐标系走。点「返回主页面」或按 Esc 回到主页。</p>"),
    ("图层对比", "<p><b>做什么</b></p><p>按图层名和 KMZ 文件夹名比较要素数量与 Name，或只按点、线、面统计数量，或比较图层名称与字段（含字段顺序）。名称要完全一致。要素数为 0 的图层按无数据处理。</p><p><b>怎么用</b></p><p>把 KMZ 拖进虚线框，或点「选择 KMZ 文件」。对比方式顺序为：要素数量与 Name、按几何类型、图层名称与字段。点「开始对比」。图层名称与字段对比的结果以列表显示（QGIS、KMZ、类型、结果），窗口默认 700×600，可复制或导出报告。点「返回主页面」或按 Esc 回到主页。</p>"),
)


def show_help(parent=None):
    dialog = QDialog(None)
    apply_taskbar_window(dialog)
    dialog.setWindowTitle(tr("帮助"))
    dialog.resize(640, 480)
    layout = QVBoxLayout(dialog)
    tabs = QTabWidget()
    for title, body in PAGES:
        browser = QTextBrowser()
        browser.setOpenExternalLinks(False)
        browser.setHtml(tr(body))
        tabs.addTab(browser, tr(title))
    layout.addWidget(tabs, 1)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    localize_button_box(buttons)
    buttons.rejected.connect(dialog.reject)
    buttons.clicked.connect(dialog.accept)
    layout.addWidget(buttons)
    run_dialog(dialog)
