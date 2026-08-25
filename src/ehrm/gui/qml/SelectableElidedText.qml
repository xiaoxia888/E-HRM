import QtQuick
import QtQuick.Controls

Item {
    id: root

    property string text: ""
    property color textColor: "#303744"
    property int pixelSize: 13
    property int horizontalAlignment: Text.AlignLeft
    property bool emphasized: false
    signal doubleClicked()

    Text {
        id: displayText
        anchors.fill: parent
        verticalAlignment: Text.AlignVCenter
        horizontalAlignment: root.horizontalAlignment
        text: root.text
        color: root.textColor
        font.pixelSize: root.pixelSize
        font.weight: root.emphasized ? Font.Medium : Font.Normal
        elide: Text.ElideRight
        maximumLineCount: 1
        visible: !copyEditor.activeFocus
    }

    TextInput {
        id: copyEditor
        anchors.fill: parent
        verticalAlignment: TextInput.AlignVCenter
        horizontalAlignment: root.horizontalAlignment
        text: root.text
        color: root.textColor
        font.pixelSize: root.pixelSize
        font.weight: root.emphasized ? Font.Medium : Font.Normal
        readOnly: true
        selectByMouse: true
        persistentSelection: true
        autoScroll: false
        clip: true
        selectionColor: "#b9d8ff"
        selectedTextColor: "#172033"
        opacity: activeFocus ? 1 : 0
        onActiveFocusChanged: {
            if (!activeFocus)
                deselect()
        }

        TapHandler {
            acceptedButtons: Qt.LeftButton
            acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
            exclusiveSignals: TapHandler.DoubleTap
            onDoubleTapped: root.doubleClicked()
        }
    }

    HoverHandler {
        id: textHover
        acceptedDevices: PointerDevice.Mouse
    }

    ToolTip {
        visible: textHover.hovered && displayText.truncated && !copyEditor.activeFocus
        delay: 300
        timeout: 12000
        y: root.height + 3
        contentItem: Text {
            width: Math.min(430, Math.max(160, implicitWidth))
            text: root.text
            color: "#f8fafc"
            font.pixelSize: 13
            wrapMode: Text.WrapAnywhere
        }
        background: Rectangle {
            color: "#243247"
            radius: 7
            border.color: "#3d4c61"
        }
    }
}
