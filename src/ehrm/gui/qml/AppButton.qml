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
    color: !enabled
        ? control.danger ? "#f1e5e5" : "#e7eaf0"
        : control.danger
            ? mouseArea.pressed ? "#b42318"
                : mouseArea.containsMouse ? "#ef5b61"
                : "#e5484d"
        : control.primary
            ? mouseArea.pressed ? "#0958d9"
                : mouseArea.containsMouse ? "#3b8cff"
                : "#1677ff"
        : mouseArea.containsMouse ? "#f7faff" : "#ffffff"
    border.width: 1
    border.color: !enabled
        ? control.danger ? "#dfcccc" : "#d5dae2"
        : control.danger ? "#e5484d"
        : (control.primary || control.outline || mouseArea.containsMouse) ? "#1677ff"
        : "#d9dde5"

    Behavior on color {
        ColorAnimation { duration: 110 }
    }

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
            color: !control.enabled
                ? control.danger ? "#a77b7b" : "#858f9e"
                : control.primary || control.danger ? "#ffffff"
                : control.outline ? "#1677ff"
                : "#1f2329"
            font.pixelSize: 15
            font.weight: Font.Medium
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        enabled: control.enabled
        hoverEnabled: true
        cursorShape: control.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: control.clicked()
    }
}
