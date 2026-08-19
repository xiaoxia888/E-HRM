import QtQuick
import QtQuick.Layouts

Item {
    id: page
    property string title: ""
    property string subtitle: ""
    property string description: ""

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 32
        spacing: 8
        Text {
            text: page.title
            color: "#1d2433"
            font.pixelSize: 25
            font.weight: Font.Bold
        }
        Text {
            text: page.subtitle
            color: "#6b7380"
            font.pixelSize: 14
        }
        Item { Layout.preferredHeight: 10 }
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            radius: 10
            color: "#ffffff"
            border.color: "#e1e5eb"
            Column {
                anchors.fill: parent
                anchors.margins: 30
                spacing: 12
                Text {
                    text: "功能预留"
                    color: "#202632"
                    font.pixelSize: 18
                    font.weight: Font.Bold
                }
                Text {
                    width: parent.width
                    text: page.description
                    color: "#6b7380"
                    font.pixelSize: 14
                    wrapMode: Text.WordWrap
                }
            }
        }
    }
}

