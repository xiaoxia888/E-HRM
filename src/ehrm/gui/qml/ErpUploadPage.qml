import QtQuick
import QtQuick as QQ
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: page
    required property var backend

    FileDialog {
        id: uploadFileDialog
        title: "选择需要上传至 ERP 的文件"
        currentFolder: appBackend.downloadsFolderUrl
        nameFilters: [
            "支持的文件 (*.pdf *.doc *.docx *.xls *.xlsx *.xlsm)",
            "PDF 文件 (*.pdf)",
            "Word 文件 (*.doc *.docx)",
            "Excel 文件 (*.xls *.xlsx *.xlsm)"
        ]
        fileMode: FileDialog.OpenFile
        onAccepted: appBackend.selectErpUploadFile(selectedFile)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 105
            color: "#f9fbfd"
            border.color: "#d6dde7"
            Column {
                anchors.left: parent.left
                anchors.leftMargin: 32
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                Text {
                    text: "上传至 ERP"
                    color: "#1d2433"
                    font.pixelSize: 25
                    font.weight: Font.Bold
                }
                Text {
                    text: "选择文件，匹配任务编号并上传至人力资源事务申请"
                    color: "#6b7380"
                    font.pixelSize: 14
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 24
            Layout.topMargin: 20
            spacing: 16

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 78
                radius: 9
                color: "#fbfcfe"
                border.color: "#d3dbe6"

                RowLayout {
                    anchors.centerIn: parent
                    spacing: 18
                    Repeater {
                        model: [
                            { number: "1", label: "选择文件", active: true },
                            { number: "2", label: "填写任务编号", active: appBackend.erpFileSelected },
                            { number: "3", label: "确认上传", active: appBackend.erpUploading }
                        ]
                        RowLayout {
                            id: stepItem
                            required property int index
                            required property var modelData
                            spacing: 9
                            Rectangle {
                                width: 32
                                height: 32
                                radius: 16
                                color: stepItem.modelData.active ? "#1677ff" : "#ffffff"
                                border.color: stepItem.modelData.active ? "#1677ff" : "#b8c2cf"
                                Text {
                                    anchors.centerIn: parent
                                    text: stepItem.modelData.number
                                    color: stepItem.modelData.active ? "#ffffff" : "#7a8493"
                                    font.pixelSize: 14
                                    font.weight: Font.DemiBold
                                }
                            }
                            Text {
                                text: stepItem.modelData.label
                                color: stepItem.modelData.active ? "#1677ff" : "#6f7887"
                                font.pixelSize: 14
                                font.weight: stepItem.modelData.active ? Font.DemiBold : Font.Normal
                            }
                            Rectangle {
                                visible: stepItem.index < 2
                                Layout.preferredWidth: 112
                                Layout.preferredHeight: 2
                                color: stepItem.modelData.active ? "#1677ff" : "#cfd7e2"
                            }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 18

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    radius: 10
                    color: "#fbfcfe"
                    border.color: "#d3dbe6"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 15

                        Text {
                            text: "待上传文件"
                            color: "#202632"
                            font.pixelSize: 18
                            font.weight: Font.Bold
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: appBackend.erpFileSelected ? 88 : 0
                            visible: appBackend.erpFileSelected
                            radius: 8
                            color: "#ffffff"
                            border.color: "#cfd8e4"

                            RowLayout {
                                anchors.fill: parent
                                anchors.margins: 14
                                spacing: 13
                                Rectangle {
                                    Layout.preferredWidth: 48
                                    Layout.preferredHeight: 54
                                    radius: 7
                                    color: "#eaf3ff"
                                    Image {
                                        anchors.centerIn: parent
                                        width: 27
                                        height: 27
                                        source: "../assets/document.svg"
                                    }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 5
                                    Text {
                                        Layout.fillWidth: true
                                        text: appBackend.erpFileName
                                        color: "#263142"
                                        font.pixelSize: 15
                                        font.weight: Font.DemiBold
                                        elide: Text.ElideMiddle
                                    }
                                    Text {
                                        text: appBackend.erpFileDetails
                                        color: "#748094"
                                        font.pixelSize: 13
                                    }
                                }
                                Text {
                                    text: "✓ 文件校验通过"
                                    color: "#12a150"
                                    font.pixelSize: 13
                                    font.weight: Font.Medium
                                }
                                AppButton {
                                    text: "重新选择"
                                    enabled: !appBackend.erpUploading
                                    onClicked: uploadFileDialog.open()
                                }
                            }
                        }

                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 170
                            radius: 9
                            color: "#f7faff"
                            border.width: 1
                            border.color: "#91bfff"

                            Column {
                                anchors.centerIn: parent
                                spacing: 11
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "+"
                                    color: "#1677ff"
                                    font.pixelSize: 30
                                    font.weight: Font.Light
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: appBackend.erpFileSelected ? "选择其他文件" : "选择上传文件"
                                    color: "#1677ff"
                                    font.pixelSize: 17
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    text: "支持 PDF、Word 和 Excel 文件"
                                    color: "#7a8493"
                                    font.pixelSize: 13
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: !appBackend.erpUploading
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: uploadFileDialog.open()
                            }
                        }

                        Item { Layout.fillHeight: true }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            Text {
                                text: appBackend.erpUploadStatus
                                color: appBackend.erpUploading ? "#1677ff" : "#687181"
                                font.pixelSize: 13
                            }
                            ProgressBar {
                                Layout.fillWidth: true
                                visible: appBackend.erpUploading
                                indeterminate: true
                            }
                        }
                    }
                }

                Rectangle {
                    Layout.preferredWidth: 330
                    Layout.fillHeight: true
                    radius: 10
                    color: "#fbfcfe"
                    border.color: "#d3dbe6"

                    ColumnLayout {
                        anchors.fill: parent
                        anchors.margins: 20
                        spacing: 14
                        Text {
                            text: "上传说明"
                            color: "#202632"
                            font.pixelSize: 18
                            font.weight: Font.Bold
                        }
                        Repeater {
                            model: [
                                ["支持的文件格式", "PDF、Word（doc/docx）、Excel（xls/xlsx/xlsm）"],
                                ["任务编号精确匹配", "任务编号必须与 ERP 人力资源事务申请一致"],
                                ["上传后写入附件", "文件将作为附件写入匹配的 ERP 申请记录"]
                            ]
                            Rectangle {
                                id: instructionItem
                                required property var modelData
                                Layout.fillWidth: true
                                Layout.preferredHeight: 104
                                radius: 8
                                color: "#f7f9fc"
                                border.color: "#d7e0ea"
                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 14
                                    spacing: 8
                                    Text {
                                        text: instructionItem.modelData[0]
                                        color: "#2f3847"
                                        font.pixelSize: 14
                                        font.weight: Font.DemiBold
                                    }
                                    Text {
                                        width: parent.width
                                        text: instructionItem.modelData[1]
                                        color: "#788395"
                                        font.pixelSize: 12
                                        wrapMode: Text.WordWrap
                                    }
                                }
                            }
                        }
                        Item { Layout.fillHeight: true }
                    }
                }
            }
        }
    }

    Dialog {
        id: taskNumberDialog
        width: 540
        height: 430
        x: Math.round((page.width - width) / 2)
        y: Math.round((page.height - height) / 2)
        modal: true
        focus: true
        padding: 24
        closePolicy: Popup.CloseOnEscape
        background: Rectangle {
            color: "#ffffff"
            radius: 11
            border.color: "#cfd8e4"
        }
        onOpened: taskNumberInput.forceActiveFocus()

        contentItem: ColumnLayout {
            spacing: 15
            Text {
                text: "确认上传至 ERP"
                color: "#202632"
                font.pixelSize: 21
                font.weight: Font.Bold
            }
            Text { text: "已选择文件"; color: "#667085"; font.pixelSize: 13 }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 52
                radius: 7
                color: "#f7f9fc"
                border.color: "#d7e0ea"
                Text {
                    anchors.fill: parent
                    anchors.margins: 12
                    verticalAlignment: Text.AlignVCenter
                    text: appBackend.erpFileName
                    color: "#303744"
                    font.pixelSize: 14
                    elide: Text.ElideMiddle
                }
            }
            Text { text: "任务编号"; color: "#303744"; font.pixelSize: 14; font.weight: Font.Medium }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 43
                radius: 7
                color: "#ffffff"
                border.width: 1
                border.color: taskNumberInput.activeFocus
                    ? "#9aa9bb"
                    : taskNumberMouse.hovered ? "#aeb9c7" : "#cbd5e1"
                clip: true

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 14
                    anchors.verticalCenter: parent.verticalCenter
                    text: "例如：RLSQ20260819-0001"
                    visible: taskNumberInput.text.length === 0
                    color: "#9aa4b2"
                    font.pixelSize: 14
                }

                QQ.TextInput {
                    id: taskNumberInput
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 14
                    verticalAlignment: QQ.TextInput.AlignVCenter
                    activeFocusOnTab: true
                    selectByMouse: true
                    color: "#202632"
                    selectionColor: "#b9d8ff"
                    selectedTextColor: "#152033"
                    font.pixelSize: 15
                    maximumLength: 80
                    validator: RegularExpressionValidator {
                        regularExpression: /[A-Za-z0-9_-]{1,80}/
                    }
                }

                HoverHandler {
                    id: taskNumberMouse
                }
            }
            Text {
                Layout.fillWidth: true
                text: "将通过任务编号精确匹配人力资源事务申请"
                color: "#7a8493"
                font.pixelSize: 12
            }
            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 48
                radius: 7
                color: "#fff8e8"
                border.color: "#ffc866"
                Text {
                    anchors.fill: parent
                    anchors.margins: 11
                    verticalAlignment: Text.AlignVCenter
                    text: "上传前请确认任务编号与所选文件一致"
                    color: "#9a6200"
                    font.pixelSize: 13
                }
            }
            Row {
                Layout.alignment: Qt.AlignRight
                spacing: 10
                AppButton { text: "取消"; onClicked: taskNumberDialog.close() }
                AppButton {
                    text: "确认上传"
                    primary: true
                    enabled: taskNumberInput.acceptableInput && taskNumberInput.text.trim().length > 0
                    onClicked: {
                        appBackend.uploadSelectedFileToErp(taskNumberInput.text)
                        taskNumberDialog.close()
                    }
                }
            }
        }
    }

    Dialog {
        id: uploadResultDialog
        width: 560
        height: 330
        x: Math.round((page.width - width) / 2)
        y: Math.round((page.height - height) / 2)
        modal: true
        padding: 24
        property string heading: ""
        property string message: ""
        property string details: ""
        background: Rectangle { color: "#ffffff"; radius: 11; border.color: "#cfd8e4" }
        contentItem: ColumnLayout {
            spacing: 15
            Text { text: uploadResultDialog.heading; color: "#202632"; font.pixelSize: 21; font.weight: Font.Bold }
            Text { Layout.fillWidth: true; text: uploadResultDialog.message; color: "#303744"; font.pixelSize: 15; wrapMode: Text.WordWrap }
            Rectangle {
                Layout.fillWidth: true
                Layout.fillHeight: true
                radius: 7
                color: "#f7f9fc"
                border.color: "#d7e0ea"
                Text {
                    anchors.fill: parent
                    anchors.margins: 12
                    text: uploadResultDialog.details
                    color: "#697386"
                    font.pixelSize: 13
                    wrapMode: Text.WrapAnywhere
                }
            }
            Row {
                Layout.alignment: Qt.AlignRight
                AppButton { text: "确定"; primary: true; onClicked: uploadResultDialog.close() }
            }
        }
    }

    Connections {
        target: appBackend
        function onErpFileReady() {
            taskNumberInput.clear()
            taskNumberDialog.open()
        }
        function onManualErpUploadFinished(title, message, details) {
            uploadResultDialog.heading = title
            uploadResultDialog.message = message
            uploadResultDialog.details = details
            uploadResultDialog.open()
        }
    }
}
