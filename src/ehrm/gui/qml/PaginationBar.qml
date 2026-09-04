pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: control

    property int totalCount: 0
    property int currentPage: 1
    property int totalPages: 1
    property int pageSize: 20
    property var pageSizeOptions: [10, 20, 50, 100]
    property bool busy: false
    property bool compact: false

    signal pageRequested(int pageNumber)
    signal pageSizeRequested(int pageSize)

    readonly property var visiblePageNumbers: {
        const total = Math.max(1, totalPages)
        let first = Math.max(1, currentPage - 2)
        let last = Math.min(total, first + 4)
        first = Math.max(1, last - 4)
        const pages = []
        for (let page = first; page <= last; page += 1)
            pages.push(page)
        return pages
    }

    implicitHeight: compact ? 44 : 48

    component PageButton: Rectangle {
        id: pageButton
        property string label: ""
        property bool selected: false
        property bool available: true
        signal clicked()

        Layout.preferredWidth: control.compact ? 32 : 36
        Layout.preferredHeight: control.compact ? 30 : 34
        radius: 7
        color: selected
            ? "#1677ff"
            : buttonMouse.containsMouse && available ? "#f4f8ff" : "#ffffff"
        border.width: 1
        border.color: selected
            ? "#1677ff"
            : buttonMouse.containsMouse && available ? "#91caff" : "#d9dde5"
        opacity: available ? 1 : 0.48

        Behavior on color { ColorAnimation { duration: 100 } }

        Text {
            anchors.centerIn: parent
            text: pageButton.label
            color: pageButton.selected ? "#ffffff" : "#303846"
            font.pixelSize: control.compact ? 12 : 13
            font.weight: pageButton.selected ? Font.DemiBold : Font.Normal
        }

        MouseArea {
            id: buttonMouse
            anchors.fill: parent
            enabled: pageButton.available
            hoverEnabled: true
            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
            onClicked: pageButton.clicked()
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: control.compact ? 5 : 6

        Item { Layout.fillWidth: true }

        Text {
            text: "共 " + control.totalCount + " 条"
            color: "#3d4654"
            font.pixelSize: control.compact ? 12 : 13
        }

        PageButton {
            label: "‹"
            available: !control.busy && control.currentPage > 1
            onClicked: control.pageRequested(control.currentPage - 1)
        }

        Repeater {
            model: control.visiblePageNumbers
            delegate: PageButton {
                required property int modelData
                label: String(modelData)
                selected: modelData === control.currentPage
                available: !control.busy
                onClicked: control.pageRequested(modelData)
            }
        }

        PageButton {
            label: "›"
            available: !control.busy
                && control.currentPage < Math.max(1, control.totalPages)
            onClicked: control.pageRequested(control.currentPage + 1)
        }

        Rectangle {
            id: pageSizeButton
            Layout.preferredWidth: control.compact ? 92 : 104
            Layout.preferredHeight: control.compact ? 30 : 34
            radius: 7
            color: sizeMouse.containsMouse && !control.busy
                ? "#f7faff" : "#ffffff"
            border.width: 1
            border.color: sizePopup.opened || sizeMouse.containsMouse
                ? "#91caff" : "#d9dde5"
            opacity: control.busy ? 0.55 : 1

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 11
                anchors.rightMargin: 9
                spacing: 5
                Text {
                    Layout.fillWidth: true
                    text: control.pageSize + " 条/页"
                    color: "#303846"
                    font.pixelSize: control.compact ? 12 : 13
                }
                Text {
                    text: sizePopup.opened ? "⌃" : "⌄"
                    color: "#6b7380"
                    font.pixelSize: 13
                }
            }

            MouseArea {
                id: sizeMouse
                anchors.fill: parent
                enabled: !control.busy
                hoverEnabled: true
                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                onClicked: sizePopup.opened ? sizePopup.close() : sizePopup.open()
            }

            Popup {
                id: sizePopup
                parent: pageSizeButton
                x: 0
                y: -height - 6
                width: pageSizeButton.width
                height: optionColumn.implicitHeight + 8
                padding: 4
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

                background: Rectangle {
                    radius: 8
                    color: "#ffffff"
                    border.color: "#d9dde5"
                    layer.enabled: true
                }

                contentItem: Column {
                    id: optionColumn
                    Repeater {
                        model: control.pageSizeOptions
                        delegate: Rectangle {
                            id: optionItem
                            required property int modelData
                            width: sizePopup.availableWidth
                            height: control.compact ? 32 : 36
                            radius: 5
                            color: modelData === control.pageSize
                                ? "#e8f3ff"
                                : optionMouse.containsMouse ? "#f5f7fa" : "transparent"

                            Text {
                                anchors.centerIn: parent
                                text: optionItem.modelData + " 条/页"
                                color: optionItem.modelData === control.pageSize
                                    ? "#1677ff" : "#303846"
                                font.pixelSize: control.compact ? 12 : 13
                                font.weight: optionItem.modelData === control.pageSize
                                    ? Font.DemiBold : Font.Normal
                            }

                            MouseArea {
                                id: optionMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: {
                                    sizePopup.close()
                                    if (optionItem.modelData !== control.pageSize)
                                        control.pageSizeRequested(optionItem.modelData)
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
