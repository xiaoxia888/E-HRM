import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Rectangle {
    id: root
    property string value: ""
    property string placeholderText: "年 / 月 / 日"
    property int displayedYear: new Date().getFullYear()
    property int displayedMonth: new Date().getMonth()
    signal valueEdited(string value)

    implicitHeight: 44
    radius: 7
    color: "#ffffff"
    border.color: editor.activeFocus || calendarPopup.opened ? "#1677ff" : "#cbd5e1"
    border.width: editor.activeFocus || calendarPopup.opened ? 2 : 1

    function setDate(dateValue) {
        var formatted = Qt.formatDate(dateValue, "yyyy-MM-dd")
        root.value = formatted
        editor.text = formatted
        root.valueEdited(formatted)
    }

    function clearFocus() {
        editor.focus = false
    }

    function daysInDisplayedMonth() {
        return new Date(displayedYear, displayedMonth + 1, 0).getDate()
    }

    function firstDayOffset() {
        var sundayBased = new Date(displayedYear, displayedMonth, 1).getDay()
        return (sundayBased + 6) % 7
    }

    function dayAt(index) {
        var day = index - firstDayOffset() + 1
        return day >= 1 && day <= daysInDisplayedMonth() ? day : 0
    }

    function moveMonth(offset) {
        var next = new Date(displayedYear, displayedMonth + offset, 1)
        displayedYear = next.getFullYear()
        displayedMonth = next.getMonth()
    }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: 12
        anchors.rightMargin: 8
        spacing: 6

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true
            TextInput {
                id: editor
                anchors.fill: parent
                verticalAlignment: TextInput.AlignVCenter
                text: root.value
                maximumLength: 10
                font.pixelSize: 14
                color: "#283243"
                selectByMouse: true
                clip: true
                onTextEdited: {
                    root.value = text
                    root.valueEdited(text)
                }
            }
            Text {
                anchors.fill: parent
                verticalAlignment: Text.AlignVCenter
                text: root.placeholderText
                color: "#9aa3b1"
                font.pixelSize: 14
                visible: editor.text.length === 0 && !editor.activeFocus
            }
        }

        Rectangle {
            Layout.preferredWidth: 34
            Layout.preferredHeight: 34
            radius: 6
            color: calendarMouse.containsMouse ? "#e8f3ff" : "#f3f6fa"
            border.color: "#d4dde8"
            Text {
                anchors.centerIn: parent
                text: "日"
                color: "#52708f"
                font.pixelSize: 12
                font.weight: Font.DemiBold
            }
            MouseArea {
                id: calendarMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: calendarPopup.opened ? calendarPopup.close() : calendarPopup.open()
            }
        }
    }

    Popup {
        id: calendarPopup
        x: 0
        y: root.height + 5
        width: 300
        height: 308
        padding: 12
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        background: Rectangle {
            color: "#ffffff"
            radius: 9
            border.color: "#d5dde8"
        }

        contentItem: ColumnLayout {
            spacing: 8
            RowLayout {
                Layout.fillWidth: true
                Rectangle {
                    Layout.preferredWidth: 32
                    Layout.preferredHeight: 30
                    radius: 5
                    color: previousMouse.containsMouse ? "#edf4fc" : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "‹"
                        color: "#46566b"
                        font.pixelSize: 21
                    }
                    MouseArea {
                        id: previousMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.moveMonth(-1)
                    }
                }
                Text {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    text: root.displayedYear + " 年 " + (root.displayedMonth + 1) + " 月"
                    color: "#253044"
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                }
                Rectangle {
                    Layout.preferredWidth: 32
                    Layout.preferredHeight: 30
                    radius: 5
                    color: nextMouse.containsMouse ? "#edf4fc" : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "›"
                        color: "#46566b"
                        font.pixelSize: 21
                    }
                    MouseArea {
                        id: nextMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.moveMonth(1)
                    }
                }
            }

            Row {
                Layout.fillWidth: true
                Repeater {
                    model: ["一", "二", "三", "四", "五", "六", "日"]
                    Text {
                        required property string modelData
                        width: calendarPopup.availableWidth / 7
                        height: 22
                        text: modelData
                        color: "#7c8796"
                        font.pixelSize: 12
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }

            Grid {
                Layout.fillWidth: true
                Layout.fillHeight: true
                columns: 7
                Repeater {
                    model: 42
                    Rectangle {
                        id: dayCell
                        required property int index
                        property int dayNumber: root.dayAt(index)
                        property string dateText: dayNumber > 0
                            ? root.displayedYear + "-"
                              + String(root.displayedMonth + 1).padStart(2, "0") + "-"
                              + String(dayNumber).padStart(2, "0")
                            : ""
                        width: calendarPopup.availableWidth / 7
                        height: 27
                        radius: 5
                        color: root.value === dateText && dayNumber > 0
                            ? "#1677ff"
                            : dayNumber > 0 && dayMouse.containsMouse ? "#edf5ff" : "transparent"
                        Text {
                            anchors.centerIn: parent
                            text: dayCell.dayNumber > 0 ? dayCell.dayNumber : ""
                            color: root.value === dayCell.dateText ? "#ffffff" : "#283243"
                            font.pixelSize: 13
                        }
                        MouseArea {
                            id: dayMouse
                            anchors.fill: parent
                            enabled: dayCell.dayNumber > 0
                            hoverEnabled: true
                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: {
                                root.value = dayCell.dateText
                                editor.text = dayCell.dateText
                                root.valueEdited(dayCell.dateText)
                                calendarPopup.close()
                            }
                        }
                    }
                }
            }

            AppButton {
                Layout.alignment: Qt.AlignRight
                text: "清空"
                onClicked: {
                    root.value = ""
                    editor.text = ""
                    root.valueEdited("")
                    calendarPopup.close()
                }
            }
        }
    }
}
