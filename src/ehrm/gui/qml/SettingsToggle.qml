import QtQuick

Item {
    id: control

    property bool checked: false
    property string text: ""
    property string description: ""
    signal toggled(bool checked)

    implicitHeight: description.length > 0 ? 56 : 38
    implicitWidth: 360
    opacity: enabled ? 1 : 0.55

    Row {
        anchors.fill: parent
        spacing: 12

        Rectangle {
            id: indicator
            anchors.top: parent.top
            anchors.topMargin: 4
            width: 20
            height: 20
            radius: 5
            color: control.checked ? "#1677ff" : "#ffffff"
            border.width: 1
            border.color: control.checked ? "#1677ff" : "#b8c4d2"

            Text {
                anchors.centerIn: parent
                visible: control.checked
                text: "✓"
                color: "#ffffff"
                font.pixelSize: 14
                font.weight: Font.Bold
            }
        }

        Column {
            width: parent.width - indicator.width - parent.spacing
            spacing: 5
            Text {
                width: parent.width
                text: control.text
                color: "#273142"
                font.pixelSize: 15
                font.weight: Font.Medium
                wrapMode: Text.WordWrap
            }
            Text {
                width: parent.width
                visible: control.description.length > 0
                text: control.description
                color: "#7b8798"
                font.pixelSize: 12
                wrapMode: Text.WordWrap
            }
        }
    }

    MouseArea {
        anchors.fill: parent
        enabled: control.enabled
        hoverEnabled: true
        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: control.toggled(!control.checked)
    }
}
