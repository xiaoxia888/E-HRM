pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    objectName: "nocobaseApplicationDetailDialog"
    required property var backend
    readonly property var detail: backend ? backend.nocobaseApplicationDetail : ({})
    readonly property var people: backend ? backend.nocobaseApplicationPeople : []
    property int peoplePage: 1
    property int peoplePageSize: 10
    readonly property int peopleTotalPages: Math.max(
        1, Math.ceil(people.length / peoplePageSize)
    )
    readonly property int peoplePageStart: (peoplePage - 1) * peoplePageSize
    readonly property var pagedPeople: people.slice(
        peoplePageStart, peoplePageStart + peoplePageSize
    )

    onPeopleChanged: peoplePage = 1
    onPeoplePageSizeChanged: peoplePage = 1

    width: parent
        ? Math.min(820, Math.max(560, parent.width * 0.45))
        : 820
    height: parent ? parent.height : 800
    x: parent ? parent.width - width : 0
    y: 0
    modal: true
    focus: true
    padding: 0
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        color: "#ffffff"
        border.color: "#dfe3e8"
    }

    component FieldLabel: Text {
        color: "#252d3a"
        font.pixelSize: 13
        font.weight: Font.DemiBold
    }

    component ReadOnlyField: Rectangle {
        property string value: ""
        property bool muted: false
        Layout.fillWidth: true
        Layout.preferredHeight: 38
        radius: 5
        color: muted ? "#f6f7f9" : "#ffffff"
        border.color: "#d9dee7"
        Text {
            anchors.fill: parent
            anchors.leftMargin: 11
            anchors.rightMargin: 11
            verticalAlignment: Text.AlignVCenter
            text: parent.value || "-"
            color: parent.muted ? "#8a94a3" : "#303846"
            font.pixelSize: 13
            elide: Text.ElideRight
        }
    }

    contentItem: ColumnLayout {
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            color: "#ffffff"
            border.color: "#edf0f4"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 20
                Text {
                    text: "查看权益申请"
                    color: "#1f2937"
                    font.pixelSize: 19
                    font.weight: Font.Bold
                }
                Item { Layout.fillWidth: true }
            }
        }

        Item {
            Layout.fillWidth: true
            Layout.fillHeight: true

            BusyIndicator {
                anchors.centerIn: parent
                running: dialog.backend.nocobaseApplicationDetailLoading
                visible: running
            }

            Column {
                anchors.centerIn: parent
                width: Math.min(parent.width - 60, 520)
                spacing: 12
                visible: !dialog.backend.nocobaseApplicationDetailLoading
                    && dialog.backend.nocobaseApplicationDetailError.length > 0
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: "详情加载失败"
                    color: "#d4380d"
                    font.pixelSize: 19
                    font.weight: Font.Bold
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WrapAnywhere
                    text: dialog.backend.nocobaseApplicationDetailError
                    color: "#687386"
                    font.pixelSize: 13
                }
            }

            ScrollView {
                id: detailScroll
                anchors.fill: parent
                anchors.margins: 18
                clip: true
                visible: !dialog.backend.nocobaseApplicationDetailLoading
                    && dialog.backend.nocobaseApplicationDetailError.length === 0
                    && Object.keys(dialog.detail).length > 0
                ScrollBar.horizontal.policy: ScrollBar.AlwaysOff

                ColumnLayout {
                    width: detailScroll.availableWidth
                    spacing: 13

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: formColumn.implicitHeight + 30
                        radius: 8
                        color: "#ffffff"
                        border.color: "#e4e8ef"

                        ColumnLayout {
                            id: formColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 15
                            spacing: 11

                            FieldLabel { text: "标题" }
                            ReadOnlyField { value: dialog.detail.title || "" }
                            FieldLabel { text: "事务类型" }
                            ReadOnlyField { value: dialog.detail.problemTypeLabel || "" }

                            GridLayout {
                                Layout.fillWidth: true
                                columns: 2
                                columnSpacing: 16
                                rowSpacing: 8
                                FieldLabel { text: "编号" }
                                FieldLabel { text: "录入人" }
                                ReadOnlyField { value: dialog.detail.code || ""; muted: true }
                                ReadOnlyField { value: dialog.detail.createdBy || ""; muted: true }
                                FieldLabel { text: "录入日期" }
                                FieldLabel { text: "状态" }
                                ReadOnlyField { value: dialog.detail.createdAt || ""; muted: true }
                                ReadOnlyField { value: dialog.detail.statusLabel || ""; muted: true }
                                FieldLabel { text: "发起人" }
                                FieldLabel { text: "发起日期" }
                                ReadOnlyField { value: dialog.detail.initiator || "" }
                                ReadOnlyField { value: dialog.detail.initiationDate || "" }
                                FieldLabel { text: "预计完成工时" }
                                FieldLabel { text: "实际工时" }
                                ReadOnlyField { value: dialog.detail.estimateTime || "" }
                                ReadOnlyField { value: dialog.detail.actualTime || "" }
                                FieldLabel { text: "预计完成日期" }
                                FieldLabel { text: "实际完成日期" }
                                ReadOnlyField { value: dialog.detail.estimateDate || ""; muted: true }
                                ReadOnlyField { value: dialog.detail.actualDate || ""; muted: true }
                            }

                            FieldLabel { text: "事务/问题描述" }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 92
                                radius: 5
                                color: "#ffffff"
                                border.color: "#d9dee7"
                                Text {
                                    anchors.fill: parent
                                    anchors.margins: 11
                                    text: dialog.detail.problemDescription || "暂无内容"
                                    color: dialog.detail.problemDescription ? "#303846" : "#98a2b3"
                                    wrapMode: Text.WrapAnywhere
                                    font.pixelSize: 13
                                }
                            }

                            FieldLabel { text: "处理方式" }
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 92
                                radius: 5
                                color: "#ffffff"
                                border.color: "#d9dee7"
                                Text {
                                    anchors.fill: parent
                                    anchors.margins: 11
                                    text: dialog.detail.handlingMethod || "暂无内容"
                                    color: dialog.detail.handlingMethod ? "#303846" : "#98a2b3"
                                    wrapMode: Text.WrapAnywhere
                                    font.pixelSize: 13
                                }
                            }
                        }
                    }

                    FieldLabel { text: "申请人员（" + dialog.people.length + " 人）" }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 92
                            + Math.min(dialog.people.length, 10) * 42
                        Layout.minimumHeight: 134
                        color: "#ffffff"
                        border.color: "#e4e8ef"
                        clip: true

                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 0

                            Flickable {
                                id: peopleFlick
                                objectName: "nocobaseApplicationPeopleFlick"
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                readonly property var columnWidths: [
                                    50, 85, 75, 210, 145, 90, 180, 105, 105
                                ]
                                readonly property real baseTableWidth: 1045
                                readonly property real columnScale: width >= baseTableWidth
                                    ? width / baseTableWidth : 1
                                readonly property real tableWidth: baseTableWidth * columnScale
                                contentWidth: tableWidth
                                contentHeight: peopleTable.height
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
                                ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                                ScrollBar.vertical: ScrollBar {
                                    policy: peopleFlick.contentHeight > peopleFlick.height
                                        ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
                                }

                                Column {
                                    id: peopleTable
                                    width: peopleFlick.tableWidth
                                    Row {
                                        Repeater {
                                            model: ["序号", "打印组", "险种", "单位", "部门", "姓名", "身份证号", "起始月份", "结束月份"]
                                            delegate: Rectangle {
                                                required property int index
                                                required property string modelData
                                                width: peopleFlick.columnWidths[index]
                                                    * peopleFlick.columnScale
                                                height: 42
                                                color: "#fafafa"
                                                border.color: "#edf0f4"
                                                Text {
                                                    anchors.fill: parent
                                                    anchors.leftMargin: 9
                                                    verticalAlignment: Text.AlignVCenter
                                                    text: parent.modelData
                                                    color: "#303846"
                                                    font.pixelSize: 12
                                                    font.weight: Font.DemiBold
                                                }
                                            }
                                        }
                                    }
                                    Repeater {
                                        model: dialog.pagedPeople
                                        delegate: Row {
                                            id: personRow
                                            required property int index
                                            required property var modelData
                                            property var values: [
                                                String(dialog.peoplePageStart + index + 1),
                                                modelData.printGroup,
                                                modelData.insuranceLabel,
                                                modelData.company, modelData.department,
                                                modelData.name, modelData.identity,
                                                modelData.startMonth, modelData.endMonth
                                            ]
                                            Repeater {
                                                model: personRow.values
                                                delegate: Rectangle {
                                                    required property int index
                                                    required property string modelData
                                                    width: peopleFlick.columnWidths[index]
                                                        * peopleFlick.columnScale
                                                    height: 42
                                                    color: "#ffffff"
                                                    border.color: "#edf0f4"
                                                    Text {
                                                        anchors.fill: parent
                                                        anchors.leftMargin: 9
                                                        anchors.rightMargin: 7
                                                        verticalAlignment: Text.AlignVCenter
                                                        text: parent.modelData
                                                        color: "#303846"
                                                        font.pixelSize: 12
                                                        elide: Text.ElideRight
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            PaginationBar {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 50
                                totalCount: dialog.people.length
                                currentPage: dialog.peoplePage
                                totalPages: dialog.peopleTotalPages
                                pageSize: dialog.peoplePageSize
                                pageSizeOptions: [10, 20, 50]
                                compact: true
                                onPageRequested: function(pageNumber) {
                                    dialog.peoplePage = pageNumber
                                    peopleFlick.contentY = 0
                                }
                                onPageSizeRequested: function(newPageSize) {
                                    dialog.peoplePageSize = newPageSize
                                    peopleFlick.contentY = 0
                                }
                            }
                        }
                    }

                    FieldLabel { text: "附件" }
                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 64
                        radius: 6
                        color: "#fafbfc"
                        border.color: "#e4e8ef"
                        Text {
                            anchors.fill: parent
                            anchors.margins: 12
                            verticalAlignment: Text.AlignVCenter
                            text: dialog.detail.attachmentCount > 0
                                ? dialog.detail.attachmentNames.join("、") : "暂无附件"
                            color: dialog.detail.attachmentCount > 0 ? "#303846" : "#98a2b3"
                            elide: Text.ElideRight
                            font.pixelSize: 13
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        Layout.bottomMargin: 10
                        Item { Layout.fillWidth: true }
                        AppButton {
                            text: "打印社保权益单"
                            primary: true
                            enabled: dialog.people.length > 0
                                && !dialog.backend.running
                            onClicked: dialog.backend.startNocobaseApplicationPrint()
                        }
                    }
                }
            }
        }
    }
}
