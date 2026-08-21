import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    required property var backend
    property int filterRowNumber: 0
    property var displayedIssues: {
        var source = dialog.backend ? dialog.backend.recordIssues : []
        if (dialog.filterRowNumber <= 0)
            return source
        return source.filter(function(item) {
            return Number(item.rowNumber || 0) === dialog.filterRowNumber
        })
    }

    function actionableCount() {
        var count = 0
        for (var index = 0; index < displayedIssues.length; ++index) {
            var level = displayedIssues[index].level
            if (level === "error" || level === "warning" || level === "pending")
                count += 1
        }
        return count
    }

    function openForRow(rowNumber) {
        filterRowNumber = Number(rowNumber || 0)
        open()
    }

    width: Math.min(820, Overlay.overlay.width - 40)
    height: Math.min(560, Overlay.overlay.height - 32)
    x: Math.round((Overlay.overlay.width - width) / 2)
    y: Math.round((Overlay.overlay.height - height) / 2)
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape
    onClosed: filterRowNumber = 0
    background: Rectangle {
        color: "#ffffff"
        radius: 12
        border.color: "#d7dee8"
    }

    contentItem: ColumnLayout {
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 92
            color: "#f7f9fc"
            radius: 12
            Column {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                anchors.leftMargin: 26
                spacing: 5
                Text {
                    text: dialog.filterRowNumber > 0 ? "当前行详情" : "问题明细"
                    color: "#1f2937"
                    font.pixelSize: 22
                    font.weight: Font.Bold
                }
                Text {
                    text: "共 " + dialog.displayedIssues.length
                          + " 条信息，其中 "
                          + dialog.actionableCount()
                          + " 项需要处理。"
                    color: "#697386"
                    font.pixelSize: 13
                }
            }
        }

        ListView {
            id: issueList
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 20
            spacing: 9
            clip: true
            model: dialog.displayedIssues
            delegate: Rectangle {
                id: issueRow
                required property var modelData
                width: issueList.width
                height: issueContent.implicitHeight + 24
                radius: 8
                color: modelData.level === "error" ? "#fff6f5"
                    : modelData.level === "warning" ? "#fffaf0" : "#f4f8fd"
                border.color: modelData.level === "error" ? "#f0b4ae"
                    : modelData.level === "warning" ? "#efd08a" : "#c7d8eb"

                ColumnLayout {
                    id: issueContent
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 12
                    spacing: 6

                    RowLayout {
                        Layout.fillWidth: true
                        Rectangle {
                            Layout.preferredWidth: levelText.implicitWidth + 14
                            Layout.preferredHeight: 24
                            radius: 12
                            color: issueRow.modelData.level === "error" ? "#d92d20"
                                : issueRow.modelData.level === "warning" ? "#d98b00" : "#3b78b4"
                            Text {
                                id: levelText
                                anchors.centerIn: parent
                                text: issueRow.modelData.levelLabel
                                color: "#ffffff"
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: issueRow.modelData.taskNumber + "  ·  "
                                  + issueRow.modelData.personName
                            color: "#253044"
                            font.pixelSize: 14
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Text {
                            text: issueRow.modelData.code
                            color: "#7b8797"
                            font.pixelSize: 11
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: issueRow.modelData.message
                        color: "#344054"
                        font.pixelSize: 14
                        font.weight: Font.Medium
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        Layout.fillWidth: true
                        text: issueRow.modelData.details
                        color: "#667085"
                        font.pixelSize: 13
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 66
            color: "#f8fafc"
            border.color: "#e0e6ee"
            AppButton {
                anchors.right: parent.right
                anchors.rightMargin: 24
                anchors.verticalCenter: parent.verticalCenter
                text: "关闭"
                primary: true
                onClicked: dialog.close()
            }
        }
    }
}
