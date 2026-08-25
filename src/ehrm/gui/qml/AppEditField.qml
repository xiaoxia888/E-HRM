import QtQuick

Rectangle {
    id: control

    property alias text: editor.text
    property string placeholderText: ""
    property bool readOnly: false
    property int maximumLength: 32767

    implicitHeight: 44
    radius: 7
    color: control.readOnly ? "#f5f7fa" : "#ffffff"
    border.width: editor.activeFocus ? 2 : 1
    border.color: editor.activeFocus ? "#1677ff" : "#cbd5e1"

    function focusEditor() {
        editor.forceActiveFocus()
        editor.selectAll()
    }

    TextInput {
        id: editor
        anchors.fill: parent
        anchors.leftMargin: 13
        anchors.rightMargin: 13
        verticalAlignment: TextInput.AlignVCenter
        color: control.readOnly ? "#6f7a8a" : "#1f2937"
        font.pixelSize: 14
        readOnly: control.readOnly
        selectByMouse: true
        clip: true
        maximumLength: control.maximumLength
        selectionColor: "#b9d8ff"
        selectedTextColor: "#172033"
    }

    Text {
        anchors.fill: parent
        anchors.leftMargin: 13
        anchors.rightMargin: 13
        verticalAlignment: Text.AlignVCenter
        visible: editor.text.length === 0 && !editor.activeFocus
        text: control.placeholderText
        color: "#9aa6b6"
        font.pixelSize: 14
        elide: Text.ElideRight
    }
}
