import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    objectName: "nocobasePrintProgressDialog"
    required property var backend
    signal previewRequested()

    readonly property bool active: backend
        && (backend.nocobasePrintState === "running"
            || backend.nocobasePrintState === "stopping")
    readonly property bool completed: backend
        && backend.nocobasePrintState === "completed"
    readonly property bool stopped: backend
        && backend.nocobasePrintState === "stopped"
    readonly property bool failed: backend
        && backend.nocobasePrintState === "failed"

    width: Math.min(650, parent ? parent.width - 40 : 650)
    height: 430
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.round((parent.height - height) / 2) : 0
    modal: true
    focus: true
    padding: 26
    closePolicy: active ? Popup.NoAutoClose : Popup.CloseOnEscape

    background: Rectangle {
        color: "#ffffff"
        radius: 12
        border.color: "#d7dee8"
    }

    contentItem: ColumnLayout {
        spacing: 16

        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 54

            RowLayout {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.rightMargin: closeButton.visible ? 46 : 0
                anchors.verticalCenter: parent.verticalCenter
                spacing: 13

                BusyIndicator {
                    Layout.preferredWidth: 38
                    Layout.preferredHeight: 38
                    running: dialog.active
                    visible: running
                }
                Rectangle {
                    visible: !dialog.active
                    Layout.preferredWidth: 38
                    Layout.preferredHeight: 38
                    radius: 19
                    color: dialog.completed ? "#e9f8ef"
                        : (dialog.stopped ? "#fff7e6" : "#fff1f0")
                    Text {
                        anchors.centerIn: parent
                        text: dialog.completed ? "✓" : (dialog.stopped ? "■" : "!")
                        color: dialog.completed ? "#12a150"
                            : (dialog.stopped ? "#d48806" : "#cf1322")
                        font.pixelSize: 21
                        font.weight: Font.Bold
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 3
                    Text {
                        text: dialog.active
                            ? (dialog.backend.stopping ? "正在安全停止" : "正在打印社保权益单")
                            : (dialog.completed ? "权益单打印完成"
                                : (dialog.stopped ? "权益单打印已停止" : "权益单打印失败"))
                        color: "#1f2937"
                        font.pixelSize: 21
                        font.weight: Font.Bold
                    }
                    Text {
                        text: dialog.active
                            ? "运行期间弹窗不可关闭；需要中止时请点击停止任务。"
                            : "任务已经结束，现在可以关闭弹窗。"
                        color: "#737d8d"
                        font.pixelSize: 13
                    }
                }
            }

            Item {
                id: closeButton
                objectName: "nocobasePrintCloseButton"
                visible: !dialog.active
                width: 32
                height: 32
                anchors.top: parent.top
                anchors.right: parent.right

                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: closeMouse.containsMouse ? "#f1f4f8" : "transparent"
                    Behavior on color { ColorAnimation { duration: 100 } }
                }
                Text {
                    anchors.centerIn: parent
                    text: "×"
                    color: closeMouse.containsMouse ? "#1f2937" : "#667085"
                    font.pixelSize: 22
                    font.weight: Font.Normal
                }
                MouseArea {
                    id: closeMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: dialog.close()
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 124
            radius: 8
            color: dialog.failed ? "#fff7f6" : "#f5f8fc"
            border.color: dialog.failed ? "#ffccc7" : "#dce4ee"
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 8
                Text {
                    Layout.fillWidth: true
                    text: dialog.backend ? dialog.backend.nocobasePrintMessage : ""
                    color: dialog.failed ? "#cf1322" : "#39475a"
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                    wrapMode: Text.WrapAnywhere
                }
                Text {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    visible: dialog.backend && dialog.backend.nocobasePrintDetails.length > 0
                    text: dialog.backend ? dialog.backend.nocobasePrintDetails : ""
                    color: "#667286"
                    font.pixelSize: 12
                    wrapMode: Text.WrapAnywhere
                    elide: Text.ElideRight
                    maximumLineCount: 4
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: "处理进度"
                color: "#4b5565"
                font.pixelSize: 13
            }
            Item { Layout.fillWidth: true }
            Text {
                text: (dialog.backend ? dialog.backend.progressCurrent : 0)
                    + " / " + (dialog.backend ? dialog.backend.progressTotal : 0)
                color: "#1677ff"
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 9
            radius: 5
            color: "#e6ebf2"
            Rectangle {
                height: parent.height
                width: parent.width * Math.min(
                    1,
                    (dialog.backend ? dialog.backend.progressCurrent : 0)
                    / Math.max(1, dialog.backend ? dialog.backend.progressTotal : 1)
                )
                radius: 5
                color: dialog.failed ? "#ff4d4f" : "#1677ff"
                Behavior on width { NumberAnimation { duration: 180 } }
            }
        }

        Item { Layout.fillHeight: true }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            AppButton {
                visible: dialog.active
                text: dialog.backend && dialog.backend.stopping
                    ? "正在停止…" : "停止任务"
                danger: true
                enabled: dialog.backend && dialog.backend.nocobasePrintRunning
                    && !dialog.backend.stopping
                onClicked: dialog.backend.requestStop()
            }
            AppButton {
                objectName: "nocobasePrintPreviewButton"
                visible: !dialog.active && dialog.backend.hasPreviewablePdfs
                text: "预览 PDF"
                primary: true
                onClicked: dialog.previewRequested()
            }
            AppButton {
                visible: !dialog.active && dialog.backend.lastOutputPath.length > 0
                text: "打开文件夹"
                outline: true
                onClicked: dialog.backend.openFolder(dialog.backend.lastOutputPath)
            }
        }
    }
}
