import QtQuick

Rectangle {
    id: control
    property alias title: titleText.text
    property alias helper: helperText.text
    property bool selected: false
    signal clicked()

    implicitHeight: 126
    radius: 9
    color: control.selected ? "#f5f9ff" : mouseArea.containsMouse ? "#fafcff" : "#ffffff"
    border.width: control.selected ? 2 : 1
    border.color: control.selected ? "#1677ff" : "#dfe3e8"

    Row {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 13
        Rectangle {
            width: 20
            height: 20
            radius: 10
            color: "#ffffff"
            border.width: control.selected ? 6 : 1
            border.color: control.selected ? "#1677ff" : "#b9c0ca"
        }
        Column {
            width: parent.width - 34
            spacing: 13
            Text {
                id: titleText
                width: parent.width
                color: "#202532"
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }
            Text {
                id: helperText
                width: parent.width
                color: "#7a8290"
                font.pixelSize: 13
            }
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: control.clicked()
    }
}
