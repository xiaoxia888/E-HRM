pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: page
    objectName: "nocobaseApplicationsPage"
    required property var backend

    readonly property int rowHeight: 46
    readonly property int headerHeight: 44
    component HeaderCell: Rectangle {
        property string label: ""
        property real cellWidth: 100
        width: cellWidth
        height: page.headerHeight
        color: "#fafafa"
        border.color: "#edf0f4"
        Text {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 8
            verticalAlignment: Text.AlignVCenter
            text: parent.label
            color: "#262f3d"
            font.pixelSize: 13
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
    }

    component BodyCell: Item {
        property string value: ""
        property real cellWidth: 100
        property color textColor: "#303846"
        width: cellWidth
        height: page.rowHeight
        Text {
            anchors.fill: parent
            anchors.leftMargin: 10
            anchors.rightMargin: 8
            verticalAlignment: Text.AlignVCenter
            text: parent.value
            color: parent.textColor
            font.pixelSize: 13
            elide: Text.ElideRight
            ToolTip.visible: cellHover.containsMouse && truncated
            ToolTip.text: text
            MouseArea {
                id: cellHover
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Column {
                spacing: 3
                Text {
                    text: "人力资源事务申请"
                    color: "#1d2433"
                    font.pixelSize: 24
                    font.weight: Font.Bold
                }
                Text {
                    text: "单位社保权益单申请"
                    color: "#6b7380"
                    font.pixelSize: 13
                }
            }
            Item { Layout.fillWidth: true }
        }

        Rectangle {
            id: listCard
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 240
            radius: 9
            color: "#ffffff"
            border.color: "#e2e6ec"
            clip: true

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 0

                RowLayout {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 46
                    spacing: 10
                    BusyIndicator {
                        Layout.preferredWidth: 20
                        Layout.preferredHeight: 20
                        running: page.backend.nocobaseApplicationsLoading
                        visible: running
                    }
                    Rectangle {
                        visible: !page.backend.nocobaseApplicationsLoading
                        Layout.preferredWidth: 8
                        Layout.preferredHeight: 8
                        radius: 4
                        color: page.backend.nocobaseApplicationsCount > 0
                            ? "#12a150" : "#98a2b3"
                    }
                    Text {
                        text: page.backend.nocobaseApplicationsStatus
                        color: "#5f6b7a"
                        font.pixelSize: 13
                        elide: Text.ElideRight
                        Layout.maximumWidth: 520
                    }
                    Item { Layout.fillWidth: true }

                    AppButton {
                        Layout.preferredHeight: 36
                        text: page.backend.nocobaseApplicationsLoading
                            ? "加载中…" : "刷新"
                        enabled: !page.backend.nocobaseApplicationsLoading
                        onClicked: page.backend.loadNocobaseApplications(
                            page.backend.nocobaseApplicationsPage
                        )
                    }
                }

                Rectangle {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: "#ffffff"
                    border.color: "#edf0f4"
                    clip: true

                    Flickable {
                        id: tableFlick
                        objectName: "nocobaseApplicationsTableFlick"
                        anchors.fill: parent
                        readonly property real baseTableWidth: 1330
                        readonly property real columnScale: width >= 1100
                            ? width / baseTableWidth : 1
                        readonly property real tableWidth: baseTableWidth * columnScale
                        contentWidth: tableWidth
                        contentHeight: tableContent.height
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        onWidthChanged: {
                            const maximum = Math.max(0, contentWidth - width)
                            contentX = Math.max(0, Math.min(contentX, maximum))
                        }
                        onContentWidthChanged: {
                            const maximum = Math.max(0, contentWidth - width)
                            contentX = Math.max(0, Math.min(contentX, maximum))
                        }
                        ScrollBar.horizontal: ScrollBar {
                            policy: tableFlick.contentWidth > tableFlick.width + 1
                                ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                        }
                        ScrollBar.vertical: ScrollBar {
                            policy: tableFlick.contentHeight > tableFlick.height
                                ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                        }

                        Column {
                            id: tableContent
                            width: tableFlick.tableWidth

                            Row {
                                HeaderCell { label: "序号"; cellWidth: 50 * tableFlick.columnScale }
                                HeaderCell { label: "编号"; cellWidth: 180 * tableFlick.columnScale }
                                HeaderCell { label: "状态"; cellWidth: 74 * tableFlick.columnScale }
                                HeaderCell { label: "标题"; cellWidth: 180 * tableFlick.columnScale }
                                HeaderCell { label: "事务类型"; cellWidth: 130 * tableFlick.columnScale }
                                HeaderCell { label: "发起人"; cellWidth: 90 * tableFlick.columnScale }
                                HeaderCell { label: "发起日期"; cellWidth: 105 * tableFlick.columnScale }
                                HeaderCell { label: "预计完成工时"; cellWidth: 110 * tableFlick.columnScale }
                                HeaderCell { label: "实际工时"; cellWidth: 90 * tableFlick.columnScale }
                                HeaderCell { label: "预计完成日期"; cellWidth: 125 * tableFlick.columnScale }
                                HeaderCell { label: "实际完成日期"; cellWidth: 126 * tableFlick.columnScale }
                                HeaderCell { label: "操作"; cellWidth: 70 * tableFlick.columnScale }
                            }

                            Repeater {
                                model: page.backend.nocobaseApplications
                                delegate: Rectangle {
                                    id: applicationRow
                                    required property int index
                                    required property var modelData
                                    width: tableFlick.tableWidth
                                    height: page.rowHeight
                                    color: rowMouse.containsMouse ? "#f5f9ff" : "#ffffff"
                                    border.color: "#edf0f4"

                                    Row {
                                        anchors.fill: parent
                                        BodyCell {
                                            cellWidth: 50 * tableFlick.columnScale
                                            value: String(
                                                (page.backend.nocobaseApplicationsPage - 1)
                                                * page.backend.nocobaseApplicationsPageSize
                                                + applicationRow.index + 1
                                            )
                                        }
                                        BodyCell { cellWidth: 180 * tableFlick.columnScale; value: applicationRow.modelData.code }
                                        Item {
                                            width: 74 * tableFlick.columnScale
                                            height: page.rowHeight
                                            Rectangle {
                                                anchors.left: parent.left
                                                anchors.leftMargin: 8
                                                anchors.verticalCenter: parent.verticalCenter
                                                width: statusText.implicitWidth + 14
                                                height: 26
                                                radius: 4
                                                color: "#fafafa"
                                                border.color: "#d9dde5"
                                                Text {
                                                    id: statusText
                                                    anchors.centerIn: parent
                                                    text: applicationRow.modelData.statusLabel
                                                    color: "#394150"
                                                    font.pixelSize: 12
                                                }
                                            }
                                        }
                                        BodyCell { cellWidth: 180 * tableFlick.columnScale; value: applicationRow.modelData.title }
                                        BodyCell { cellWidth: 130 * tableFlick.columnScale; value: applicationRow.modelData.problemTypeLabel }
                                        BodyCell { cellWidth: 90 * tableFlick.columnScale; value: applicationRow.modelData.initiator; textColor: "#1677ff" }
                                        BodyCell { cellWidth: 105 * tableFlick.columnScale; value: applicationRow.modelData.initiationDate }
                                        BodyCell { cellWidth: 110 * tableFlick.columnScale; value: applicationRow.modelData.estimateTime }
                                        BodyCell { cellWidth: 90 * tableFlick.columnScale; value: applicationRow.modelData.actualTime }
                                        BodyCell { cellWidth: 125 * tableFlick.columnScale; value: applicationRow.modelData.estimateDate }
                                        BodyCell { cellWidth: 126 * tableFlick.columnScale; value: applicationRow.modelData.actualDate }
                                        Item {
                                            width: 70 * tableFlick.columnScale
                                            height: page.rowHeight
                                            AppButton {
                                                anchors.centerIn: parent
                                                width: 52
                                                height: 30
                                                text: "查看"
                                                primary: true
                                                enabled: !page.backend.nocobaseApplicationDetailLoading
                                                onClicked: page.backend.loadNocobaseApplicationDetail(
                                                    applicationRow.modelData.id
                                                )
                                            }
                                        }
                                    }

                                    MouseArea {
                                        id: rowMouse
                                        anchors.fill: parent
                                        hoverEnabled: true
                                        acceptedButtons: Qt.NoButton
                                    }
                                }
                            }
                        }

                        Text {
                            anchors.centerIn: parent
                            visible: !page.backend.nocobaseApplicationsLoading
                                && page.backend.nocobaseApplications.length === 0
                            text: "暂无权益申请数据"
                            color: "#98a2b3"
                            font.pixelSize: 14
                        }
                    }
                }

                PaginationBar {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 46
                    totalCount: page.backend.nocobaseApplicationsCount
                    currentPage: page.backend.nocobaseApplicationsPage
                    totalPages: Math.max(
                        1, page.backend.nocobaseApplicationsTotalPage
                    )
                    pageSize: page.backend.nocobaseApplicationsPageSize
                    busy: page.backend.nocobaseApplicationsLoading
                    onPageRequested: function(pageNumber) {
                        page.backend.loadNocobaseApplications(pageNumber)
                    }
                    onPageSizeRequested: function(newPageSize) {
                        page.backend.setNocobaseApplicationsPageSize(newPageSize)
                    }
                }
            }
        }

    }
}
