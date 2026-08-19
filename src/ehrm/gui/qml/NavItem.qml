import QtQuick

Rectangle {
    id: control
    property alias text: title.text
    property url iconSource: ""
    property bool selected: false
    property bool reserved: false
    signal clicked()

    implicitHeight: 52
    radius: 8
    color: control.selected ? "#eaf3ff" : mouseArea.containsMouse ? "#f5f8fc" : "transparent"

    Rectangle {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: 4
        height: control.selected ? 34 : 0
        radius: 2
        color: "#1677ff"
    }

    Row {
        anchors.left: parent.left
        anchors.leftMargin: 18
        anchors.verticalCenter: parent.verticalCenter
        spacing: 12
        Image {
            width: 20
            height: 20
            source: control.iconSource
            fillMode: Image.PreserveAspectFit
        }
        Text {
            id: title
            anchors.verticalCenter: parent.verticalCenter
            color: control.selected ? "#1677ff" : "#303540"
            font.pixelSize: 15
            font.weight: control.selected ? Font.DemiBold : Font.Normal
        }
        Rectangle {
            visible: control.reserved
            anchors.verticalCenter: parent.verticalCenter
            width: reservedText.implicitWidth + 12
            height: 24
            radius: 5
            color: "#f2f3f5"
            border.color: "#d9dde5"
            Text {
                id: reservedText
                anchors.centerIn: parent
                text: "预留"
                color: "#6b7280"
                font.pixelSize: 12
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
