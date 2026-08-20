import QtQuick

Rectangle {
    id: control

    property int value: 50
    property int from: 1
    property int to: 100
    property string unit: "人"
    signal valueEdited(int value)

    implicitWidth: 170
    implicitHeight: 42
    radius: 7
    color: control.enabled ? "#ffffff" : "#f5f6f8"
    border.color: editor.activeFocus ? "#1677ff" : "#d9dde5"
    border.width: editor.activeFocus ? 2 : 1
    opacity: control.enabled ? 1 : 0.55

    function commit(rawValue) {
        const parsed = Number(rawValue)
        const normalized = isNaN(parsed)
            ? control.value
            : Math.max(control.from, Math.min(control.to, Math.round(parsed)))
        editor.text = normalized.toString()
        if (normalized !== control.value)
            control.valueEdited(normalized)
    }

    onValueChanged: {
        if (!editor.activeFocus)
            editor.text = control.value.toString()
    }

    Row {
        anchors.fill: parent

        Rectangle {
            width: 40
            height: parent.height
            radius: control.radius
            color: minusArea.pressed ? "#eaf3ff" : minusArea.containsMouse ? "#f3f7fc" : "transparent"
            Text {
                anchors.centerIn: parent
                text: "−"
                color: control.value > control.from && control.enabled ? "#303744" : "#b8bec8"
                font.pixelSize: 20
            }
            MouseArea {
                id: minusArea
                anchors.fill: parent
                enabled: control.enabled && control.value > control.from
                hoverEnabled: true
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: control.valueEdited(control.value - 1)
            }
        }

        Rectangle {
            width: 88
            height: parent.height
            color: "transparent"
            border.color: "#edf0f3"
            border.width: 1
            Row {
                anchors.centerIn: parent
                spacing: 5
                TextInput {
                    id: editor
                    width: control.unit === "毫秒" ? 52 : 39
                    text: control.value.toString()
                    enabled: control.enabled
                    color: "#202632"
                    font.pixelSize: 15
                    font.weight: Font.DemiBold
                    horizontalAlignment: TextInput.AlignRight
                    verticalAlignment: TextInput.AlignVCenter
                    selectByMouse: true
                    validator: IntValidator { bottom: control.from; top: control.to }
                    onEditingFinished: control.commit(text)
                    Keys.onReturnPressed: {
                        control.commit(text)
                        focus = false
                    }
                }
                Text {
                    text: control.unit
                    color: "#596273"
                    font.pixelSize: 14
                }
            }
        }

        Rectangle {
            width: 40
            height: parent.height
            radius: control.radius
            color: plusArea.pressed ? "#eaf3ff" : plusArea.containsMouse ? "#f3f7fc" : "transparent"
            Text {
                anchors.centerIn: parent
                text: "+"
                color: control.value < control.to && control.enabled ? "#303744" : "#b8bec8"
                font.pixelSize: 20
            }
            MouseArea {
                id: plusArea
                anchors.fill: parent
                enabled: control.enabled && control.value < control.to
                hoverEnabled: true
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: control.valueEdited(control.value + 1)
            }
        }
    }
}
