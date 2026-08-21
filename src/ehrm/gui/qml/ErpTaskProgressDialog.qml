import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    objectName: "erpTaskProgressDialog"
    required property var backend

    width: Math.min(610, Overlay.overlay.width - 40)
    height: 386
    x: Math.round((Overlay.overlay.width - width) / 2)
    y: Math.round((Overlay.overlay.height - height) / 2)
    modal: true
    focus: true
    padding: 26
    closePolicy: Popup.NoAutoClose
    background: Rectangle {
        color: "#ffffff"
        radius: 12
        border.color: "#d7dee8"
    }

    contentItem: ColumnLayout {
        spacing: 17

        RowLayout {
            Layout.fillWidth: true
            spacing: 14
            Item {
                id: spinner
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
                    running: dialog.backend
                             ? dialog.backend.erpTaskExtractionRunning : false
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3
                Text {
                    text: dialog.backend && dialog.backend.erpTaskExtractionStopping
                        ? "正在安全停止"
                        : "正在获取并解析申请信息"
                    color: "#1f2937"
                    font.pixelSize: 21
                    font.weight: Font.Bold
                }
                Text {
                    text: dialog.backend && dialog.backend.erpTaskExtractionStopping
                        ? "当前模型请求完成后停止，已完成结果会保留。"
                        : "请保持程序运行，每条申请将顺序处理。"
                    color: "#737d8d"
                    font.pixelSize: 13
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 108
            radius: 8
            color: "#f5f8fc"
            border.color: "#dce4ee"
            Column {
                anchors.fill: parent
                anchors.margins: 13
                spacing: 8
                Text {
                    width: parent.width
                    text: "解析模型：" + (dialog.backend
                          ? dialog.backend.aiModelRuntimeLabel : "")
                    color: "#1677ff"
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                    elide: Text.ElideRight
                }
                Text {
                    width: parent.width
                    text: dialog.backend ? dialog.backend.erpTaskExtractionStatus : ""
                    color: "#39475a"
                    font.pixelSize: 14
                    elide: Text.ElideRight
                }
                Text {
                    visible: dialog.backend
                             && dialog.backend.erpTaskExtractionCurrentTask.length > 0
                    text: "当前申请：" + (dialog.backend
                          ? dialog.backend.erpTaskExtractionCurrentTask : "")
                    color: "#667286"
                    font.pixelSize: 13
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Text {
                text: dialog.backend && dialog.backend.erpTaskExtractionProgressTotal > 0
                    ? "解析进度"
                    : "正在查询 ERP 任务列表"
                color: "#4b5565"
                font.pixelSize: 13
            }
            Item { Layout.fillWidth: true }
            Text {
                visible: dialog.backend && dialog.backend.erpTaskExtractionProgressTotal > 0
                text: (dialog.backend ? dialog.backend.erpTaskExtractionProgressCurrent : 0) + " / "
                      + (dialog.backend ? dialog.backend.erpTaskExtractionProgressTotal : 0)
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
                    (dialog.backend ? dialog.backend.erpTaskExtractionProgressCurrent : 0)
                    / Math.max(1, dialog.backend ? dialog.backend.erpTaskExtractionProgressTotal : 0)
                )
                radius: 5
                color: "#1677ff"
                Behavior on width { NumberAnimation { duration: 180 } }
            }
        }

        Item { Layout.fillHeight: true }

        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            AppButton {
                text: dialog.backend && dialog.backend.erpTaskExtractionStopping
                    ? "正在停止…" : "停止任务"
                danger: true
                enabled: dialog.backend && dialog.backend.erpTaskExtractionRunning
                         && !dialog.backend.erpTaskExtractionStopping
                onClicked: dialog.backend.requestErpTaskExtractionStop()
            }
        }
    }
}
