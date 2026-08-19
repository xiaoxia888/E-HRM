import QtQuick

Rectangle {
    id: control
    property alias text: label.text
    property url iconSource: ""
    property bool primary: false
    property bool danger: false
    property bool outline: false
    signal clicked()

    implicitWidth: contentRow.implicitWidth + 34
    implicitHeight: 42
    radius: 7
    color: !enabled ? "#f2f3f5"
        : control.danger ? (mouseArea.pressed ? "#b42318" : "#e5484d")
        : control.primary ? (mouseArea.pressed ? "#0958d9" : "#1677ff")
        : mouseArea.containsMouse ? "#f7faff" : "#ffffff"
    border.width: 1
    border.color: !enabled ? "#e5e6eb"
        : control.danger ? "#e5484d"
        : (control.primary || control.outline || mouseArea.containsMouse) ? "#1677ff"
        : "#d9dde5"
    opacity: enabled ? 1 : 0.62

    Row {
        id: contentRow
        anchors.centerIn: parent
        spacing: 9
        Image {
            width: 18
            height: 18
            source: control.iconSource
            visible: source.toString().length > 0
            fillMode: Image.PreserveAspectFit
        }
        Text {
            id: label
            anchors.verticalCenter: parent.verticalCenter
            color: control.primary || control.danger ? "#ffffff" : control.outline ? "#1677ff" : "#1f2329"
            font.pixelSize: 15
            font.weight: Font.Medium
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        enabled: control.enabled
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: control.clicked()
    }
}
