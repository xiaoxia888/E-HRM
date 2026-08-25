import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Pdf

Dialog {
    id: dialog
    objectName: "pdfPreviewDialog"

    required property var backend
    property int selectedFileIndex: 0
    property url pdfSource: ""
    readonly property var files: backend ? backend.lastPdfFiles : []
    readonly property var selectedFile: files.length > selectedFileIndex
        ? files[selectedFileIndex] : ({})
    readonly property int currentPageNumber: pdfView.currentPage >= 0
        ? pdfView.currentPage + 1 : 0
    readonly property int totalPages: pdfDocument.pageCount
    readonly property int zoomPercent: Math.round(pdfView.renderScale * 100)

    width: Math.min(1280, parent ? parent.width - 36 : 1280)
    height: Math.min(820, parent ? parent.height - 32 : 820)
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.round((parent.height - height) / 2) : 0
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape

    function openPreview() {
        if (!backend || files.length === 0)
            return
        selectedFileIndex = 0
        pdfSource = files[0].url
        open()
        Qt.callLater(resetCurrentDocument)
    }

    function selectFile(index) {
        if (index < 0 || index >= files.length)
            return
        if (selectedFileIndex === index) {
            resetCurrentDocument()
            return
        }
        selectedFileIndex = index
        pdfSource = files[index].url
        Qt.callLater(resetCurrentDocument)
    }

    function resetCurrentDocument() {
        if (!opened || pdfDocument.status !== PdfDocument.Ready)
            return
        pdfView.goToPage(0)
        Qt.callLater(fitPage)
    }

    function fitPage() {
        if (pdfDocument.status !== PdfDocument.Ready
                || pdfDocument.pageCount < 1
                || previewViewport.width < 80
                || previewViewport.height < 80)
            return
        pdfView.scaleToPage(
            Math.max(80, previewViewport.width - 36),
            Math.max(80, previewViewport.height - 36)
        )
        Qt.callLater(centerPage)
    }

    function previousPage() {
        if (pdfView.currentPage > 0) {
            pdfView.goToPage(pdfView.currentPage - 1)
            Qt.callLater(centerPage)
        }
    }

    function nextPage() {
        if (pdfView.currentPage >= 0
                && pdfView.currentPage + 1 < pdfDocument.pageCount) {
            pdfView.goToPage(pdfView.currentPage + 1)
            Qt.callLater(centerPage)
        }
    }

    function zoomIn() {
        applyZoom(pdfView.renderScale * 1.2)
    }

    function zoomOut() {
        applyZoom(pdfView.renderScale / 1.2)
    }

    function handleWheelZoom(event) {
        let delta = event.angleDelta.y
        if (delta === 0)
            delta = event.pixelDelta.y
        if (delta === 0)
            return

        const factor = delta > 0 ? 1.2 : 1 / 1.2
        applyZoom(pdfView.renderScale * factor)
        event.accepted = true
    }

    function centerPage() {
        if (pdfDocument.status !== PdfDocument.Ready)
            return

        if (pdfView.contentWidth <= pdfView.width)
            pdfView.contentX = -pdfView.leftMargin
        else
            pdfView.contentX = Math.max(
                0,
                Math.min(pdfView.contentX, pdfView.contentWidth - pdfView.width)
            )

        if (pdfView.contentHeight <= pdfView.height)
            pdfView.contentY = -pdfView.topMargin
        else
            pdfView.contentY = Math.max(
                0,
                Math.min(pdfView.contentY, pdfView.contentHeight - pdfView.height)
            )
    }

    function applyZoom(nextScale) {
        if (pdfDocument.status !== PdfDocument.Ready)
            return

        const oldWidth = Math.max(1, pdfView.contentWidth)
        const oldHeight = Math.max(1, pdfView.contentHeight)
        const centerX = pdfView.contentWidth <= pdfView.width
            ? oldWidth / 2
            : pdfView.contentX + pdfView.width / 2
        const centerY = pdfView.contentHeight <= pdfView.height
            ? oldHeight / 2
            : pdfView.contentY + pdfView.height / 2
        const relativeX = centerX / oldWidth
        const relativeY = centerY / oldHeight

        pdfView.renderScale = Math.max(0.2, Math.min(5, nextScale))
        Qt.callLater(function() {
            dialog.restoreZoomCenter(relativeX, relativeY)
        })
    }

    function restoreZoomCenter(relativeX, relativeY) {
        if (pdfView.contentWidth <= pdfView.width) {
            pdfView.contentX = -pdfView.leftMargin
        } else {
            pdfView.contentX = Math.max(
                0,
                Math.min(
                    pdfView.contentWidth - pdfView.width,
                    pdfView.contentWidth * relativeX - pdfView.width / 2
                )
            )
        }

        if (pdfView.contentHeight <= pdfView.height) {
            pdfView.contentY = -pdfView.topMargin
        } else {
            pdfView.contentY = Math.max(
                0,
                Math.min(
                    pdfView.contentHeight - pdfView.height,
                    pdfView.contentHeight * relativeY - pdfView.height / 2
                )
            )
        }
    }

    onFilesChanged: {
        if (selectedFileIndex >= files.length)
            selectedFileIndex = Math.max(0, files.length - 1)
    }

    background: Rectangle {
        color: "#ffffff"
        radius: 12
        border.color: "#cfd8e4"
    }

    PdfDocument {
        id: pdfDocument
        objectName: "previewPdfDocument"
        source: dialog.pdfSource
        onStatusChanged: function(status) {
            if (status === PdfDocument.Ready)
                Qt.callLater(dialog.resetCurrentDocument)
        }
    }

    Shortcut {
        sequence: "Left"
        enabled: dialog.opened
        onActivated: dialog.previousPage()
    }
    Shortcut {
        sequence: "Right"
        enabled: dialog.opened
        onActivated: dialog.nextPage()
    }

    contentItem: ColumnLayout {
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 68
            color: "#f8fafc"
            border.color: "#dce3ec"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 22
                anchors.rightMargin: 18
                spacing: 12

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2
                    Text {
                        text: "PDF 预览"
                        color: "#202632"
                        font.pixelSize: 20
                        font.weight: Font.Bold
                    }
                    Text {
                        Layout.fillWidth: true
                        text: dialog.selectedFile.name || "未选择文件"
                        color: "#657083"
                        font.pixelSize: 13
                        elide: Text.ElideMiddle
                    }
                }

                AppButton {
                    text: "打开文件位置"
                    enabled: Boolean(dialog.selectedFile.path)
                    onClicked: dialog.backend.openFileLocation(dialog.selectedFile.path)
                }
                AppButton {
                    text: "关闭"
                    onClicked: dialog.close()
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 0

            Rectangle {
                Layout.preferredWidth: 238
                Layout.fillHeight: true
                visible: dialog.files.length > 1
                color: "#f7f9fc"
                border.color: "#dce3ec"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10
                    Text {
                        text: "本次生成文件（" + dialog.files.length + "）"
                        color: "#344054"
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    ListView {
                        id: fileList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 7
                        model: dialog.files
                        ScrollBar.vertical: ScrollBar {
                            policy: ScrollBar.AsNeeded
                        }
                        delegate: Rectangle {
                            id: fileRow
                            required property int index
                            required property var modelData
                            width: fileList.width
                            height: 64
                            radius: 7
                            color: dialog.selectedFileIndex === index
                                ? "#e8f3ff"
                                : fileMouse.containsMouse ? "#f0f5fb" : "#ffffff"
                            border.width: dialog.selectedFileIndex === index ? 2 : 1
                            border.color: dialog.selectedFileIndex === index
                                ? "#1677ff" : "#d8e0ea"

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 10
                                spacing: 9
                                Rectangle {
                                    Layout.preferredWidth: 30
                                    Layout.preferredHeight: 36
                                    radius: 5
                                    color: dialog.selectedFileIndex === fileRow.index
                                        ? "#1677ff" : "#eaf0f7"
                                    Text {
                                        anchors.centerIn: parent
                                        text: "PDF"
                                        color: dialog.selectedFileIndex === fileRow.index
                                            ? "#ffffff" : "#5d6a7c"
                                        font.pixelSize: 9
                                        font.weight: Font.Bold
                                    }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: fileRow.modelData.name
                                    color: "#303744"
                                    font.pixelSize: 13
                                    maximumLineCount: 2
                                    wrapMode: Text.WrapAnywhere
                                    elide: Text.ElideRight
                                }
                            }
                            MouseArea {
                                id: fileMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: dialog.selectFile(fileRow.index)
                            }
                            ToolTip.visible: fileMouse.containsMouse
                            ToolTip.text: fileRow.modelData.name
                            ToolTip.delay: 450
                        }
                    }
                }
            }

            Rectangle {
                id: previewViewport
                objectName: "pdfPreviewViewport"
                Layout.fillWidth: true
                Layout.fillHeight: true
                color: "#dfe4ea"
                clip: true

                PdfScrollablePageView {
                    id: pdfView
                    objectName: "previewPdfView"
                    anchors.fill: parent
                    anchors.margins: 18
                    document: pdfDocument
                    clip: true
                    leftMargin: Math.max(0, (width - contentWidth) / 2)
                    rightMargin: leftMargin
                    topMargin: Math.max(0, (height - contentHeight) / 2)
                    bottomMargin: topMargin

                    onWidthChanged: Qt.callLater(dialog.centerPage)
                    onHeightChanged: Qt.callLater(dialog.centerPage)
                    onContentWidthChanged: Qt.callLater(dialog.centerPage)
                    onContentHeightChanged: Qt.callLater(dialog.centerPage)
                }

                WheelHandler {
                    id: controlWheelZoom
                    target: null
                    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                    acceptedModifiers: Qt.ControlModifier
                    onWheel: function(event) {
                        dialog.handleWheelZoom(event)
                    }
                }

                WheelHandler {
                    id: commandWheelZoom
                    target: null
                    enabled: Qt.platform.os === "osx"
                    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                    acceptedModifiers: Qt.MetaModifier
                    onWheel: function(event) {
                        dialog.handleWheelZoom(event)
                    }
                }

                Rectangle {
                    anchors.centerIn: parent
                    width: Math.min(420, parent.width - 48)
                    height: 132
                    radius: 10
                    color: "#ffffff"
                    border.color: "#d1d9e4"
                    visible: pdfDocument.status === PdfDocument.Loading
                        || pdfDocument.status === PdfDocument.Null

                    RowLayout {
                        anchors.centerIn: parent
                        spacing: 16
                        Item {
                            id: loadingSpinner
                            Layout.preferredWidth: 38
                            Layout.preferredHeight: 38
                            Repeater {
                                model: 8
                                Rectangle {
                                    required property int index
                                    width: 4
                                    height: 10
                                    radius: 2
                                    x: 17
                                    y: 1
                                    color: "#1677ff"
                                    opacity: 0.28 + index * 0.09
                                    transform: Rotation {
                                        origin.x: 2
                                        origin.y: 18
                                        angle: index * 45
                                    }
                                }
                            }
                            RotationAnimator on rotation {
                                from: 0
                                to: 360
                                duration: 900
                                loops: Animation.Infinite
                                running: parent.visible
                            }
                        }
                        ColumnLayout {
                            spacing: 3
                            Text {
                                text: "正在加载 PDF"
                                color: "#253044"
                                font.pixelSize: 17
                                font.weight: Font.DemiBold
                            }
                            Text {
                                text: "请稍候，页面加载完成后即可翻页。"
                                color: "#707b8d"
                                font.pixelSize: 13
                            }
                        }
                    }
                }

                Rectangle {
                    anchors.centerIn: parent
                    width: Math.min(520, parent.width - 48)
                    height: 150
                    radius: 10
                    color: "#fff7f6"
                    border.color: "#e8b4ae"
                    visible: pdfDocument.status === PdfDocument.Error
                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 22
                        spacing: 8
                        Text {
                            text: "PDF 加载失败"
                            color: "#b42318"
                            font.pixelSize: 18
                            font.weight: Font.Bold
                        }
                        Text {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            text: pdfDocument.error || "文件不存在、格式无效或已经损坏。"
                            color: "#7a3d38"
                            font.pixelSize: 13
                            wrapMode: Text.WrapAnywhere
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 62
            color: "#f8fafc"
            border.color: "#dce3ec"

            RowLayout {
                anchors.centerIn: parent
                spacing: 9
                AppButton {
                    text: "上一页"
                    enabled: pdfView.currentPage > 0
                    onClicked: dialog.previousPage()
                }
                Rectangle {
                    Layout.preferredWidth: 94
                    Layout.preferredHeight: 40
                    radius: 7
                    color: "#ffffff"
                    border.color: "#d2dae5"
                    Text {
                        anchors.centerIn: parent
                        text: dialog.currentPageNumber + " / " + dialog.totalPages
                        color: "#344054"
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                }
                AppButton {
                    text: "下一页"
                    enabled: pdfView.currentPage >= 0
                        && pdfView.currentPage + 1 < pdfDocument.pageCount
                    onClicked: dialog.nextPage()
                }
                Item { Layout.preferredWidth: 14 }
                AppButton {
                    text: "－"
                    enabled: pdfDocument.status === PdfDocument.Ready
                    onClicked: dialog.zoomOut()
                }
                Text {
                    Layout.preferredWidth: 66
                    horizontalAlignment: Text.AlignHCenter
                    text: dialog.zoomPercent + "%"
                    color: "#596579"
                    font.pixelSize: 13
                }
                AppButton {
                    text: "＋"
                    enabled: pdfDocument.status === PdfDocument.Ready
                    onClicked: dialog.zoomIn()
                }
                AppButton {
                    text: "适应页面"
                    enabled: pdfDocument.status === PdfDocument.Ready
                    onClicked: dialog.fitPage()
                }
                Text {
                    text: Qt.platform.os === "osx"
                        ? "Ctrl/⌘ + 滚轮缩放"
                        : "Ctrl + 滚轮缩放"
                    color: "#8490a2"
                    font.pixelSize: 12
                }
            }
        }
    }
}
