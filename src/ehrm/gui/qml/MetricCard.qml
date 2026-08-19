import QtQuick

Rectangle {
    id: control
    property alias title: titleText.text
    property alias value: valueText.text
    property url iconSource: ""

    implicitWidth: 210
    implicitHeight: 126
    radius: 9
    color: "#f7f9fc"
    border.color: "#d3dce7"

    Row {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 17
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: 44
            height: 44
            radius: 10
            color: "#edf5ff"
            Image {
                anchors.centerIn: parent
                width: 25
                height: 25
                source: control.iconSource
                fillMode: Image.PreserveAspectFit
            }
        }
        Column {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Text {
                id: titleText
                color: "#667085"
                font.pixelSize: 14
            }
            Text {
                id: valueText
                color: "#1d2433"
                font.pixelSize: 29
                font.weight: Font.Bold
            }
        }
    }
}
