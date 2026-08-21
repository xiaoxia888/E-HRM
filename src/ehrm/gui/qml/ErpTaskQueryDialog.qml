import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    objectName: "erpTaskQueryDialog"
    required property var backend

    property bool status0: false
    property bool status15: false
    property bool status20: false
    property bool status35: false
    property bool status40: false
    property bool status50: false
    property int statusRevision: 0
    property var transactionTypes: ["社保咨询", "工资咨询", "证实咨询", "福利咨询",
                                    "合同咨询", "档案咨询", "项目社保申请挂靠", "其他咨询"]
    property int transactionTypeIndex: 0

    function selectedStatusValues() {
        var values = []
        if (status0) values.push(0)
        if (status15) values.push(15)
        if (status20) values.push(20)
        if (status35) values.push(35)
        if (status40) values.push(40)
        if (status50) values.push(50)
        return values
    }

    function statusSummary() {
        var unused = statusRevision
        var names = []
        if (status0) names.push("新增")
        if (status15) names.push("待送审")
        if (status20) names.push("审批中")
        if (status35) names.push("生效")
        if (status40) names.push("终止")
        if (status50) names.push("批准")
        return names.length ? names.join("、") : "全部状态"
    }

    function setStatus(code, checked) {
        if (code === 0) status0 = checked
        else if (code === 15) status15 = checked
        else if (code === 20) status20 = checked
        else if (code === 35) status35 = checked
        else if (code === 40) status40 = checked
        else if (code === 50) status50 = checked
        statusRevision += 1
    }

    function statusChecked(code) {
        var unused = statusRevision
        if (code === 0) return status0
        if (code === 15) return status15
        if (code === 20) return status20
        if (code === 35) return status35
        if (code === 40) return status40
        return status50
    }

    function clearInputFocus() {
        codeInput.focus = false
        startDate.clearFocus()
        endDate.clearFocus()
        dialog.forceActiveFocus(Qt.MouseFocusReason)
    }

    width: Math.min(780, Overlay.overlay.width - 40)
    height: Math.min(500, Overlay.overlay.height - 32)
    x: Math.round((Overlay.overlay.width - width) / 2)
    y: Math.round((Overlay.overlay.height - height) / 2)
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape
    onOpened: Qt.callLater(dialog.clearInputFocus)
    background: Rectangle {
        color: "#ffffff"
        radius: 12
        border.color: "#d7dee8"
    }

    contentItem: ColumnLayout {
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 96
            color: "#f7f9fc"
            radius: 12
            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 28
                anchors.rightMargin: 28
                spacing: 6
                Text {
                    text: "获取申请信息"
                    color: "#1f2937"
                    font.pixelSize: 23
                    font.weight: Font.Bold
                }
                Text {
                    text: "设置 ERP 查询条件，查询后将按顺序调用大模型解析。"
                    color: "#697386"
                    font.pixelSize: 14
                }
            }
            MouseArea {
                anchors.fill: parent
                onClicked: dialog.clearInputFocus()
            }
        }

        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: formColumn.implicitHeight + 44
            clip: true

            MouseArea {
                anchors.fill: parent
                onClicked: dialog.clearInputFocus()
            }

            ColumnLayout {
                id: formColumn
                x: 28
                y: 22
                width: parent.width - 56
                spacing: 17

                RowLayout {
                    Layout.fillWidth: true
                    spacing: 18

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 7
                        Text {
                            text: "申请编号  <font color='#8b95a5'>选填</font>"
                            textFormat: Text.RichText
                            color: "#374151"
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                        }
                        Rectangle {
                            Layout.fillWidth: true
                            Layout.preferredHeight: 44
                            radius: 7
                            color: "#ffffff"
                            border.width: codeInput.activeFocus ? 2 : 1
                            border.color: codeInput.activeFocus ? "#1677ff" : "#cbd5e1"
                            TextInput {
                                id: codeInput
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                anchors.rightMargin: 12
                                verticalAlignment: TextInput.AlignVCenter
                                color: "#283243"
                                font.pixelSize: 14
                                selectByMouse: true
                                clip: true
                            }
                            Text {
                                anchors.fill: parent
                                anchors.leftMargin: 12
                                verticalAlignment: Text.AlignVCenter
                                text: "例如 RLSQ20260818-0002"
                                color: "#9aa3b1"
                                font.pixelSize: 14
                                visible: codeInput.text.length === 0 && !codeInput.activeFocus
                            }
                        }
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 7
                        Text {
                            text: "事务类型"
                            color: "#374151"
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                        }
                        Rectangle {
                            id: transactionTypeField
                            Layout.fillWidth: true
                            Layout.preferredHeight: 44
                            radius: 7
                            color: transactionTypePopup.opened ? "#f5f9ff" : "#ffffff"
                            border.width: transactionTypePopup.opened ? 2 : 1
                            border.color: transactionTypePopup.opened ? "#1677ff" : "#cbd5e1"
                            Text {
                                anchors.left: parent.left
                                anchors.right: transactionArrow.left
                                anchors.leftMargin: 12
                                anchors.verticalCenter: parent.verticalCenter
                                text: dialog.transactionTypes[dialog.transactionTypeIndex]
                                color: "#283243"
                                font.pixelSize: 14
                                elide: Text.ElideRight
                            }
                            Text {
                                id: transactionArrow
                                anchors.right: parent.right
                                anchors.rightMargin: 13
                                anchors.verticalCenter: parent.verticalCenter
                                text: transactionTypePopup.opened ? "▴" : "▾"
                                color: "#657084"
                                font.pixelSize: 14
                            }
                            MouseArea {
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: transactionTypePopup.opened
                                    ? transactionTypePopup.close() : transactionTypePopup.open()
                            }
                            Popup {
                                id: transactionTypePopup
                                x: 0
                                y: parent.height + 5
                                width: parent.width
                                height: 4 * 36 + 12
                                padding: 6
                                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                                background: Rectangle {
                                    color: "#ffffff"
                                    radius: 8
                                    border.color: "#cbd5e1"
                                }
                                contentItem: Grid {
                                    columns: 2
                                    Repeater {
                                        model: dialog.transactionTypes
                                        delegate: Rectangle {
                                            id: transactionOption
                                            required property int index
                                            required property string modelData
                                            width: transactionTypePopup.availableWidth / 2
                                            height: 36
                                            radius: 5
                                            color: dialog.transactionTypeIndex === index
                                                ? "#e8f3ff"
                                                : transactionMouse.containsMouse ? "#f4f7fb" : "transparent"
                                            Text {
                                                anchors.left: parent.left
                                                anchors.right: selectedMark.left
                                                anchors.leftMargin: 11
                                                anchors.verticalCenter: parent.verticalCenter
                                                text: transactionOption.modelData
                                                color: "#283243"
                                                font.pixelSize: 13
                                                elide: Text.ElideRight
                                            }
                                            Text {
                                                id: selectedMark
                                                anchors.right: parent.right
                                                anchors.rightMargin: 10
                                                anchors.verticalCenter: parent.verticalCenter
                                                text: "✓"
                                                visible: dialog.transactionTypeIndex === transactionOption.index
                                                color: "#1677ff"
                                                font.pixelSize: 14
                                                font.weight: Font.Bold
                                            }
                                            MouseArea {
                                                id: transactionMouse
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: {
                                                    dialog.transactionTypeIndex = transactionOption.index
                                                    transactionTypePopup.close()
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.preferredWidth: (formColumn.width - 18) / 2
                    Layout.maximumWidth: (formColumn.width - 18) / 2
                    Layout.alignment: Qt.AlignLeft
                    spacing: 7
                    Text {
                        text: "申请状态  <font color='#8b95a5'>可多选；不选表示全部</font>"
                        textFormat: Text.RichText
                        color: "#374151"
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 44
                        radius: 7
                        color: statusPopup.opened ? "#f8fbff" : "#ffffff"
                        border.width: statusPopup.opened ? 2 : 1
                        border.color: statusPopup.opened ? "#1677ff" : "#cbd5e1"
                        Text {
                            anchors.left: parent.left
                            anchors.right: arrow.left
                            anchors.leftMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            text: dialog.statusSummary()
                            color: "#283243"
                            font.pixelSize: 14
                            elide: Text.ElideRight
                        }
                        Text {
                            id: arrow
                            anchors.right: parent.right
                            anchors.rightMargin: 13
                            anchors.verticalCenter: parent.verticalCenter
                            text: statusPopup.opened ? "▴" : "▾"
                            color: "#657084"
                            font.pixelSize: 15
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: statusPopup.opened ? statusPopup.close() : statusPopup.open()
                        }
                        Popup {
                            id: statusPopup
                            x: 0
                            y: parent.height + 5
                            width: parent.width
                            height: 132
                            padding: 10
                            closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                            background: Rectangle {
                                color: "#ffffff"
                                radius: 8
                                border.color: "#cbd5e1"
                            }
                            contentItem: ColumnLayout {
                                spacing: 4
                                GridLayout {
                                    Layout.fillWidth: true
                                    columns: 3
                                    columnSpacing: 12
                                    rowSpacing: 2
                                    Repeater {
                                        model: [
                                            {"code": 0, "name": "新增"},
                                            {"code": 15, "name": "待送审"},
                                            {"code": 20, "name": "审批中"},
                                            {"code": 35, "name": "生效"},
                                            {"code": 40, "name": "终止"},
                                            {"code": 50, "name": "批准"}
                                        ]
                                        Rectangle {
                                            id: statusOption
                                            required property var modelData
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 32
                                            radius: 5
                                            color: statusMouse.containsMouse ? "#f3f7fc" : "transparent"
                                            Row {
                                                anchors.left: parent.left
                                                anchors.verticalCenter: parent.verticalCenter
                                                spacing: 8
                                                Rectangle {
                                                    width: 18
                                                    height: 18
                                                    radius: 4
                                                    color: dialog.statusChecked(statusOption.modelData.code)
                                                        ? "#1677ff" : "#ffffff"
                                                    border.color: dialog.statusChecked(statusOption.modelData.code)
                                                        ? "#1677ff" : "#aeb9c8"
                                                    Text {
                                                        anchors.centerIn: parent
                                                        text: "✓"
                                                        visible: dialog.statusChecked(statusOption.modelData.code)
                                                        color: "#ffffff"
                                                        font.pixelSize: 12
                                                        font.weight: Font.Bold
                                                    }
                                                }
                                                Text {
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    text: statusOption.modelData.name
                                                    color: "#344054"
                                                    font.pixelSize: 13
                                                }
                                            }
                                            MouseArea {
                                                id: statusMouse
                                                anchors.fill: parent
                                                hoverEnabled: true
                                                cursorShape: Qt.PointingHandCursor
                                                onClicked: dialog.setStatus(
                                                    statusOption.modelData.code,
                                                    !dialog.statusChecked(statusOption.modelData.code)
                                                )
                                            }
                                        }
                                    }
                                }
                                RowLayout {
                                    Layout.fillWidth: true
                                    Item { Layout.fillWidth: true }
                                    AppButton {
                                        text: "清空"
                                        onClicked: {
                                            dialog.status0 = false
                                            dialog.status15 = false
                                            dialog.status20 = false
                                            dialog.status35 = false
                                            dialog.status40 = false
                                            dialog.status50 = false
                                            dialog.statusRevision += 1
                                        }
                                    }
                                    AppButton {
                                        text: "完成"
                                        primary: true
                                        onClicked: statusPopup.close()
                                    }
                                }
                            }
                        }
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 7
                    Text {
                        text: "申请日期  <font color='#8b95a5'>选填，包含起止当天</font>"
                        textFormat: Text.RichText
                        color: "#374151"
                        font.pixelSize: 14
                        font.weight: Font.DemiBold
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 10
                        DatePickerField {
                            id: startDate
                            Layout.fillWidth: true
                            onValueEdited: function(value) { startDate.value = value }
                        }
                        Text { text: "至"; color: "#737d8d"; font.pixelSize: 14 }
                        DatePickerField {
                            id: endDate
                            Layout.fillWidth: true
                            onValueEdited: function(value) { endDate.value = value }
                        }
                    }
                }

            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 68
            color: "#f8fafc"
            border.color: "#e0e6ee"
            MouseArea {
                anchors.fill: parent
                onClicked: dialog.clearInputFocus()
            }
            Row {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.rightMargin: 28
                spacing: 10
                AppButton {
                    text: "取消"
                    onClicked: dialog.close()
                }
                AppButton {
                    text: "查询并解析"
                    primary: true
                    enabled: dialog.backend && !dialog.backend.erpTaskExtractionRunning
                    onClicked: dialog.backend.startErpTaskExtraction(
                        codeInput.text,
                        dialog.selectedStatusValues().join(","),
                        dialog.transactionTypes[dialog.transactionTypeIndex],
                        startDate.value,
                        endDate.value
                    )
                }
            }
        }
    }
}
