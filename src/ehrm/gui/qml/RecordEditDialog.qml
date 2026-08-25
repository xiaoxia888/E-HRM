import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    objectName: "recordEditDialog"

    required property var backend
    property int rowNumber: 0
    property string taskNumber: ""
    property string printGroup: ""
    property string selectedInsurance: "养老"

    width: Math.min(760, parent ? parent.width - 48 : 760)
    height: Math.min(680, parent ? parent.height - 48 : 680)
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? Math.round((parent.height - height) / 2) : 0
    modal: true
    focus: true
    padding: 24
    closePolicy: Popup.CloseOnEscape

    function openForRecord(record) {
        rowNumber = record.rowNumber
        taskNumber = record.taskNumber
        printGroup = record.printGroup
        unitField.text = record.unit === "-" ? "" : record.unit
        departmentField.text = record.department === "-" ? "" : record.department
        nameField.text = record.name
        identityField.text = record.identity === "待匹配" ? "" : record.identity
        selectedInsurance = record.insurance
        startField.text = record.startMonth === "待确认" ? "" : record.startMonth
        endField.text = record.endMonth === "待确认" ? "" : record.endMonth
        errorText.text = ""
        open()
    }

    background: Rectangle {
        color: "#ffffff"
        radius: 12
        border.color: "#d6dee8"
    }

    contentItem: ColumnLayout {
        spacing: 15

        Text {
            text: "修改预览数据"
            color: "#202632"
            font.pixelSize: 22
            font.weight: Font.Bold
        }
        Text {
            Layout.fillWidth: true
            text: "修改后会重新校验。险种和起止月份将同步应用到同一打印组。"
            color: "#6b7585"
            font.pixelSize: 13
            wrapMode: Text.WordWrap
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            radius: 7
            color: "#f5f8fc"
            border.color: "#d7e0ea"
            RowLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 16
                Text {
                    Layout.fillWidth: true
                    text: "任务编号：" + dialog.taskNumber
                    color: "#344054"
                    font.pixelSize: 14
                    elide: Text.ElideRight
                }
                Text {
                    text: "打印组：" + dialog.printGroup
                    color: "#344054"
                    font.pixelSize: 14
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 16
            rowSpacing: 8

            Text { text: "单位"; color: "#344054"; font.pixelSize: 14 }
            Text { text: "部门"; color: "#344054"; font.pixelSize: 14 }
            AppEditField {
                id: unitField
                Layout.fillWidth: true
                placeholderText: "请输入单位"
            }
            AppEditField {
                id: departmentField
                Layout.fillWidth: true
                placeholderText: "请输入部门"
            }

            Text { text: "姓名"; color: "#344054"; font.pixelSize: 14 }
            Text { text: "身份证"; color: "#344054"; font.pixelSize: 14 }
            AppEditField {
                id: nameField
                Layout.fillWidth: true
                placeholderText: "请输入姓名"
            }
            AppEditField {
                id: identityField
                Layout.fillWidth: true
                placeholderText: "请输入15位或18位身份证"
                maximumLength: 18
            }
        }

        Text {
            text: "险种"
            color: "#344054"
            font.pixelSize: 14
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Repeater {
                model: ["养老", "工伤", "失业"]
                delegate: Rectangle {
                    id: insuranceOption
                    required property string modelData
                    Layout.fillWidth: true
                    Layout.preferredHeight: 42
                    radius: 7
                    color: dialog.selectedInsurance === modelData
                        ? "#eaf3ff" : insuranceMouse.containsMouse
                            ? "#f7faff" : "#ffffff"
                    border.width: dialog.selectedInsurance === modelData ? 2 : 1
                    border.color: dialog.selectedInsurance === modelData
                        ? "#1677ff" : "#cbd5e1"
                    Text {
                        anchors.centerIn: parent
                        text: insuranceOption.modelData
                        color: dialog.selectedInsurance === insuranceOption.modelData
                            ? "#1677ff" : "#344054"
                        font.pixelSize: 14
                        font.weight: dialog.selectedInsurance === insuranceOption.modelData
                            ? Font.DemiBold : Font.Normal
                    }
                    MouseArea {
                        id: insuranceMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: dialog.selectedInsurance = insuranceOption.modelData
                    }
                }
            }
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 16
            rowSpacing: 8
            Text { text: "开始时间"; color: "#344054"; font.pixelSize: 14 }
            Text { text: "结束时间"; color: "#344054"; font.pixelSize: 14 }
            AppEditField {
                id: startField
                Layout.fillWidth: true
                placeholderText: "YYYY-MM"
                maximumLength: 7
            }
            AppEditField {
                id: endField
                Layout.fillWidth: true
                placeholderText: "YYYY-MM"
                maximumLength: 7
            }
        }

        Text {
            id: errorText
            Layout.fillWidth: true
            color: "#d92d20"
            font.pixelSize: 13
            wrapMode: Text.WordWrap
        }
        Item { Layout.fillHeight: true }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: 10
            AppButton {
                text: "取消"
                onClicked: dialog.close()
            }
            AppButton {
                text: "保存修改"
                primary: true
                onClicked: {
                    const saved = dialog.backend.updateRecord(
                        dialog.rowNumber,
                        unitField.text,
                        departmentField.text,
                        nameField.text,
                        identityField.text,
                        dialog.selectedInsurance,
                        startField.text,
                        endField.text
                    )
                    if (saved)
                        dialog.close()
                }
            }
        }
    }
}
